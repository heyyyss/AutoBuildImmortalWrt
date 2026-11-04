"""Isolated certificates and state: never renew or restart the actual N1 service."""
import http.server
import importlib.util
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('idle_tls', sys.argv[1])
reload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reload)
sys.argv = [sys.argv[0], *sys.argv[2:]]


class IdleReloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='carplay-idle-reload-test-')
        cls.root = Path(cls.workspace.name)
        cls.openssl('req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256',
                    '-nodes', '-keyout', 'ca.key', '-out', 'ca.pem', '-days', '365',
                    '-subj', '/CN=Isolated Idle Reload CA',
                    '-addext', 'basicConstraints=critical,CA:TRUE',
                    '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        for key in ('first', 'rotated'):
            cls.openssl('req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256',
                        '-nodes', '-keyout', key + '.key', '-out', key + '.csr',
                        '-subj', '/CN=n1-test.example.org')
        for name, key, days, serial, host in (
            ('old', 'first', 30, 1, 'n1-test.example.org'),
            ('new', 'rotated', 90, 2, 'n1-test.example.org'),
            ('wrong', 'first', 90, 3, 'wrong.example'),
            ('expired', 'first', -1, 4, 'n1-test.example.org'),
            ('older', 'first', 10, 5, 'n1-test.example.org'),
        ):
            (cls.root / 'extensions').write_text('subjectAltName=DNS:' + host +
                '\nbasicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature\n')
            validity = (['-not_before', '20000101000000Z', '-not_after', '20010101000000Z']
                        if days < 0 else ['-days', str(days)])
            cls.openssl('x509', '-req', '-in', key + '.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
                        '-set_serial', str(serial), *validity, '-extfile', 'extensions',
                        '-out', name + '.pem')

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    @classmethod
    def openssl(cls, *args):
        return subprocess.run(['openssl', *args], cwd=cls.root, check=True,
                              capture_output=True, timeout=15).stdout

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(dir=self.root)
        self.state = Path(self.scratch.name)
        (self.state / 'tls/own').mkdir(parents=True)
        (self.state / 'receiver').mkdir()
        self.wired = self.state / 'wired.json'
        self.wired.write_text('{"phase":"cable"}')
        (self.state / 'receiver/phone-presence.json').write_text('{}')
        self.config = {'state': str(self.state), 'domain': 'n1-test.example.org',
                       'ca_file': str(self.root / 'ca.pem'), 'wired_status': str(self.wired),
                       'viewer_port': 65367, 'dashplay_root': '/opt/dashplay',
                       'service': '/etc/init.d/dashplay', 'idle_seconds': 120}
        self.candidate('old', 'first')
        reload.rebuild(self.config)
        self.old = reload.validate(self.config)
        reload.remember(self.config, self.old)
        self.previous = {'boot': 'boot-a', 'idle_since': 100}
        self.running = patch.object(reload, 'running', return_value=True)
        self.running.start()
        self.loaded = patch.object(reload, 'loaded', return_value=self.old['sha256'])
        self.loaded.start()
        self.restart = patch.object(reload, 'restart')
        self.restart_mock = self.restart.start()
        self.wait = patch.object(reload, 'wait_loaded')
        self.wait_mock = self.wait.start()

    def tearDown(self):
        self.wait.stop(); self.restart.stop(); self.loaded.stop(); self.running.stop()
        self.scratch.cleanup()

    def candidate(self, name, key):
        (self.state / reload.FILES[0]).write_bytes((self.root / (name + '.pem')).read_bytes()
                                                 + (self.root / 'ca.pem').read_bytes())
        shutil.copyfile(self.root / (key + '.key'), self.state / reload.FILES[1])

    def run_check(self, now=300, previous=None, boot='boot-a'):
        return reload.check(self.config, self.previous if previous is None else previous, now, boot)

    def test_current_certificate_never_restarts(self):
        self.assertEqual(self.run_check()['phase'], 'current')
        self.restart_mock.assert_not_called()

    def test_wireless_and_wired_activity_defer(self):
        self.candidate('new', 'rotated')
        for wireless, phase in [(True, 'cable'), (False, 'live'), (False, 'starting')]:
            (self.state / 'receiver/phone-presence.json').write_text(json.dumps({'active': 'phone' if wireless else None}))
            self.wired.write_text(json.dumps({'phase': phase}))
            result = self.run_check()
            self.assertEqual(result['phase'], 'waiting_active_carplay')
            self.assertIsNone(result['idle_since'])
        self.restart_mock.assert_not_called()

    def test_missing_or_invalid_presence_is_busy(self):
        self.candidate('new', 'rotated')
        p = self.state / 'receiver/phone-presence.json'
        p.unlink()
        self.assertEqual(self.run_check()['phase'], 'waiting_active_carplay')
        p.write_text('{')
        self.assertEqual(self.run_check()['phase'], 'waiting_active_carplay')
        self.restart_mock.assert_not_called()

    def test_grace_resets_after_reconnect_and_reboot(self):
        self.candidate('new', 'rotated')
        self.assertEqual(self.run_check(now=150)['phase'], 'waiting_idle_grace')
        self.assertEqual(self.run_check(boot='boot-b')['phase'], 'waiting_idle_grace')
        (self.state / 'receiver/phone-presence.json').write_text('{"active":"phone"}')
        busy = self.run_check()
        (self.state / 'receiver/phone-presence.json').write_text('{}')
        self.assertEqual(self.run_check(now=301, previous=busy)['phase'], 'waiting_idle_grace')
        self.restart_mock.assert_not_called()

    def test_new_certificate_and_rotated_key_load_after_idle(self):
        self.candidate('new', 'rotated')
        new = reload.validate(self.config)
        result = self.run_check()
        self.assertEqual(result['phase'], 'reloaded')
        self.restart_mock.assert_called_once()
        self.wait_mock.assert_called_once_with(self.config, new['sha256'])
        _, saved = reload.last_good(self.config)
        self.assertEqual(saved['sha256'], new['sha256'])
        self.assertEqual((self.state / reload.FILES[1]).read_bytes(), (self.root / 'rotated.key').read_bytes())

    def test_validation_rejects_bad_host_expiry_and_mismatched_key(self):
        for name, key in [('wrong', 'first'), ('expired', 'first'), ('new', 'first')]:
            self.candidate(name, key)
            with self.assertRaises(reload.ReloadError): self.run_check()
        self.restart_mock.assert_not_called()

    def test_old_certificate_cannot_replace_newer_snapshot(self):
        self.candidate('older', 'first')
        with self.assertRaisesRegex(reload.ReloadError, 'older_candidate_rejected'):
            self.run_check()
        self.restart_mock.assert_not_called()

    def test_activity_recheck_before_restart_restores_keystore_only(self):
        original = [(self.state / p).read_bytes() for p in reload.FILES]
        self.candidate('new', 'rotated')
        with patch.object(reload, 'busy', side_effect=[False, False, True]):
            result = self.run_check()
        self.assertEqual(result['phase'], 'waiting_active_carplay')
        self.assertEqual([(self.state / p).read_bytes() for p in reload.FILES[2:]], original[2:])
        self.assertNotEqual((self.state / reload.FILES[0]).read_bytes(), original[0])
        self.restart_mock.assert_not_called()

    def test_reload_failure_restores_full_previous_material_and_checks_service(self):
        old = [(self.state / p).read_bytes() for p in reload.FILES]
        self.candidate('new', 'rotated')
        self.wait_mock.side_effect = [reload.ReloadError('new service failed'), None]
        result = self.run_check()
        self.assertEqual(result['phase'], 'rolled_back')
        self.assertEqual([(self.state / p).read_bytes() for p in reload.FILES], old)
        self.assertEqual(self.restart_mock.call_count, 2)
        self.assertEqual(self.wait_mock.call_args_list[-1].args, (self.config, self.old['sha256']))
        self.assertIn('retry_after_epoch', result)

    def test_rollback_failure_reported(self):
        self.candidate('new', 'rotated')
        self.wait_mock.side_effect = reload.ReloadError('service failed')
        with self.assertRaisesRegex(reload.ReloadError, 'rollback_verification_failed'):
            self.run_check()

    def test_failed_candidate_has_retry_backoff(self):
        self.candidate('new', 'rotated')
        new = reload.validate(self.config)
        prev = {**self.previous, 'failed_candidate_sha256': new['sha256'], 'retry_after_epoch': 5000}
        with patch.object(reload.time, 'time', return_value=4000):
            self.assertEqual(self.run_check(previous=prev)['phase'], 'waiting_retry_backoff')
        self.restart_mock.assert_not_called()

    def test_stopped_service_not_started(self):
        self.candidate('new', 'rotated')
        with patch.object(reload, 'running', return_value=False):
            self.assertEqual(self.run_check()['phase'], 'service_stopped')
        self.restart_mock.assert_not_called()

    def test_missing_snapshot_does_not_restart(self):
        self.candidate('new', 'rotated')
        (self.state / 'tls/idle-reload-last-good.json').unlink()
        with self.assertRaisesRegex(reload.ReloadError, 'last_good_snapshot_unavailable'):
            self.run_check()
        self.restart_mock.assert_not_called()

    def test_unavailable_tls_without_new_certificate_does_not_restart(self):
        with patch.object(reload, 'loaded', side_effect=OSError('temporarily unavailable')):
            self.assertEqual(self.run_check()['phase'], 'waiting_service_probe')
        self.restart_mock.assert_not_called()

    def test_tls_probe_validates_actual_server_and_hostname(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def handle(self):
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The certificate-only probe intentionally sends no HTTP request.
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(self.state / reload.FILES[0]), str(self.state / reload.FILES[1]))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        # Stop only this test's loaded() mock to exercise the real TLS handshake.
        self.loaded.stop()
        try:
            config = {**self.config, 'viewer_port': server.server_port}
            self.assertEqual(reload.loaded(config), self.old['sha256'])
            with self.assertRaises(ssl.SSLCertVerificationError):
                reload.loaded({**config, 'domain': 'wrong.example'})
        finally:
            self.loaded.start()
            server.shutdown();server.server_close();thread.join(timeout=2)


unittest.main(verbosity=2)
