#!/usr/bin/python3
"""Load a renewed DuckDNS certificate only after this N1's CarPlay is idle."""
import re
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

FILES = ('tls/own/fullchain.pem', 'tls/own/key.pem',
         'receiver/tls-keystore.p12', 'tls/leaf.san.json')


class ReloadError(Exception):
    pass


def cmd(*args, data=None, timeout=20):
    return subprocess.run(args, input=data, capture_output=True, check=True, timeout=timeout).stdout


def atomic(path, content):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.idle-tls-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cert_info(chain):
    der = cmd('openssl', 'x509', '-outform', 'DER', data=chain)
    if not der:
        raise ReloadError('empty_certificate')
    raw_dates = cmd('openssl', 'x509', '-noout', '-dates', data=chain).decode()
    fields = dict(line.split('=', 1) for line in raw_dates.splitlines())
    return {'sha256': hashlib.sha256(der).hexdigest(),
            **{key: ssl.cert_time_to_seconds(fields[key]) for key in ('notBefore', 'notAfter')}}


def validate(config):
    state = Path(config['state'])
    chain, key = state / FILES[0], state / FILES[1]
    try:
        pub = cmd('openssl', 'x509', '-in', str(chain), '-pubkey', '-noout')
        cert_pub = cmd('openssl', 'pkey', '-pubin', '-outform', 'DER', data=pub)
        key_pub = cmd('openssl', 'pkey', '-in', str(key), '-pubout', '-outform', 'DER')
        if not cert_pub or cert_pub != key_pub:
            raise ReloadError('certificate_key_mismatch')
        cmd('openssl', 'verify', '-purpose', 'sslserver', '-verify_hostname', config['domain'],
            '-CAfile', config['ca_file'], '-untrusted', str(chain), str(chain))
        cmd('openssl', 'x509', '-in', str(chain), '-noout', '-checkend', '86400')
        return cert_info(chain.read_bytes())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise ReloadError('invalid_candidate_certificate') from None


def busy(config):
    try:
        presence = json.loads((Path(config['state']) / 'receiver/phone-presence.json').read_text())
        if presence.get('active'):
            return True
        wired = Path(config['wired_status'])
        if wired.exists():
            phase = json.loads(wired.read_text()).get('phase')
            if phase not in ('cable', 'idle', 'stopped', 'disconnected', 'disabled'):
                return True
        return False
    except (OSError, ValueError, TypeError):
        return True


def running(config):
    enabled = cmd('uci', '-q', 'get', 'dashplay.main.enabled').strip() == b'1'
    return enabled and subprocess.run([config['service'], 'running'], capture_output=True).returncode == 0


def loaded(config):
    context = ssl.create_default_context(cafile=config['ca_file'])
    with socket.create_connection(('127.0.0.1', int(config['viewer_port'])), timeout=3) as raw:
        with context.wrap_socket(raw, server_hostname=config['domain']) as tls:
            return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()


def wait_loaded(config, fingerprint):
    end = time.monotonic() + 35
    while time.monotonic() < end:
        try:
            if loaded(config) == fingerprint:
                return
        except (OSError, ssl.SSLError):
            pass
        time.sleep(1)
    raise ReloadError('served_certificate_verification_failed')


def restart(config):
    if not running(config):
        raise ReloadError('vehicle_mode_disabled')
    cmd(config['service'], 'restart', timeout=60)


def rebuild(config):
    cmd(sys.executable, '-c',
        'import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
        'from boxnet import ensure_leaf; '
        'ensure_leaf(Path(sys.argv[2]),[sys.argv[3]],["100.96.0.1"])',
        config['dashplay_root'], config['state'], config['domain'], timeout=45)


def remember(config, info):
    state = Path(config['state'])
    # Back up only material proven to match the certificate currently served.
    p12_cert = cmd('openssl', 'pkcs12', '-in', str(state / FILES[2]),
                   '-clcerts', '-nokeys', '-passin', 'pass:playport')
    if cert_info(p12_cert)['sha256'] != info['sha256']:
        raise ReloadError('keystore_snapshot_mismatch')
    root = state / 'tls/idle-reload-backups'
    root.mkdir(mode=0o700, exist_ok=True)
    target = root / info['sha256']
    if not target.exists():
        temporary = Path(tempfile.mkdtemp(prefix='.snapshot-', dir=root))
        try:
            for index, relative in enumerate(FILES):
                shutil.copyfile(state / relative, temporary / str(index))
                (temporary / str(index)).chmod(0o600)
            atomic(temporary / 'manifest.json', (json.dumps(info) + '\n').encode())
            temporary.rename(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    atomic(state / 'tls/idle-reload-last-good.json', (json.dumps(info) + '\n').encode())


def last_good(config):
    state = Path(config['state'])
    try:
        info = json.loads((state / 'tls/idle-reload-last-good.json').read_text())
        sha = info['sha256']
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('bad snapshot identifier')
        directory = state / 'tls/idle-reload-backups' / sha
        if cert_info((directory / '0').read_bytes())['sha256'] != sha:
            raise ValueError('bad snapshot')
        if not all((directory / str(i)).is_file() for i in range(len(FILES))):
            raise ValueError('incomplete snapshot')
        return directory, info
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise ReloadError('last_good_snapshot_unavailable') from None


def restore(config, directory, only_keystore=False):
    for index, relative in enumerate(FILES):
        if not only_keystore or index >= 2:
            atomic(Path(config['state']) / relative, (directory / str(index)).read_bytes())


def check(config, previous, now, boot):
    if not running(config):
        return {'phase': 'service_stopped', 'idle_since': None, 'boot': boot}
    info = validate(config)
    is_busy = busy(config)
    since = (previous.get('idle_since') if previous.get('boot') == boot else None)
    since = None if is_busy else (since if since is not None and since <= now else now)
    result = {'candidate_sha256': info['sha256'], 'boot': boot, 'idle_since': since}
    try:
        served = loaded(config)
    except (OSError, ssl.SSLError):
        served = None
    result['served_sha256'] = served
    if served == info['sha256']:
        remember(config, info)
        return {**result, 'phase': 'current'}
    if served is None:
        try:
            _, saved = last_good(config)
        except ReloadError:
            saved = None
        if saved is None or saved['sha256'] == info['sha256']:
            # This is a certificate loader, not a general service restart watchdog.
            return {**result, 'phase': 'waiting_service_probe'}
    if is_busy:
        return {**result, 'phase': 'waiting_active_carplay'}
    if (previous.get('failed_candidate_sha256') == info['sha256']
            and time.time() < previous.get('retry_after_epoch', 0)):
        return {**result, 'phase': 'waiting_retry_backoff'}
    if now - since < config['idle_seconds']:
        return {**result, 'phase': 'waiting_idle_grace'}
    directory, old = last_good(config)
    if info['notBefore'] < old['notBefore'] or info['notAfter'] < old['notAfter']:
        raise ReloadError('older_candidate_rejected')
    # Recheck after validation; a phone may have reconnected during this run.
    if busy(config):
        return {**result, 'phase': 'waiting_active_carplay', 'idle_since': None}
    try:
        rebuild(config)
        if busy(config):
            restore(config, directory, only_keystore=True)
            return {**result, 'phase': 'waiting_active_carplay', 'idle_since': None}
        restart(config)
        wait_loaded(config, info['sha256'])
        remember(config, info)
    except Exception:
        try:
            restore(config, directory)
            restart(config)
            wait_loaded(config, old['sha256'])
        except Exception:
            raise ReloadError('rollback_verification_failed') from None
        return {**result, 'phase': 'rolled_back', 'error': 'new_certificate_reload_failed',
                'served_sha256': old['sha256'], 'idle_since': None,
                'failed_candidate_sha256': info['sha256'],
                'retry_after_epoch': time.time() + config.get('retry_seconds', 3600)}
    return {**result, 'phase': 'reloaded', 'served_sha256': info['sha256'], 'idle_since': None}


def main():
    os.umask(0o077)
    def option(name):
        return subprocess.run(['uci', '-q', 'get', 'dashplay.main.' + name], capture_output=True, text=True).stdout.strip()
    domain = option('duckdns_domain')
    if option('enabled') != '1' or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', domain):
        return
    config = dict(domain=domain+'.duckdns.org', state='/opt/dashplay/state', dashplay_root='/opt/dashplay',
                  ca_file='/etc/ssl/certs/ca-certificates.crt', wired_status='/var/run/dashplay/wired-status.json',
                  service='/etc/init.d/dashplay', idle_seconds=120, retry_seconds=3600)
    if not (Path(config['state']) / 'tls/own/fullchain.pem').is_file():
        return
    config['viewer_port'] = int(cmd('uci', '-q', 'get', 'dashplay.main.viewer_port').strip())
    state = Path(config['state'])
    # This is the native signer's lock: do not read between its key/chain writes.
    with (state / 'acme/dashplay.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"phase":"signer_or_watcher_busy"}')
            return
        status_path = state / 'tls/idle-reload-status.json'
        try:
            previous = json.loads(status_path.read_text())
        except (OSError, ValueError):
            previous = {}
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        try:
            result = check(config, previous, time.monotonic(), boot)
        except ReloadError as error:
            result = {'phase': 'error', 'error': str(error), 'boot': boot, 'idle_since': None}
        except Exception as error:
            result = {'phase': 'error', 'error': type(error).__name__, 'boot': boot, 'idle_since': None}
        status = {k: previous[k] for k in ('last_reloaded', 'last_failure', 'last_failure_code',
                                          'failed_candidate_sha256', 'retry_after_epoch') if k in previous}
        status.update(result, last_check=now, domain=config['domain'])
        if result['phase'] == 'reloaded':
            status['last_reloaded'] = now
            status.pop('failed_candidate_sha256', None)
            status.pop('retry_after_epoch', None)
        if result['phase'] in ('error', 'rolled_back'):
            status.update(last_failure=now, last_failure_code=result.get('error'))
        atomic(status_path, (json.dumps(status, indent=2) + '\n').encode())
        changed = (result['phase'], result.get('error')) != (previous.get('phase'), previous.get('error'))
        if result['phase'] == 'reloaded' or (changed and result['phase'] in ('error', 'rolled_back')):
            subprocess.run(['logger', '-t', 'carplay-tls-idle',
                            result['phase'] + ': ' + result.get('error', result.get('served_sha256', ''))],
                           capture_output=True)
        print(json.dumps(status))
        if result['phase'] in ('error', 'rolled_back'):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
