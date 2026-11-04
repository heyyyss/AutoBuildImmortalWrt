#!/usr/bin/python3
"""Recover a replugged iPhone that last provided both wired CarPlay and tethering."""
import ctypes
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import runpy
import socket
import ssl
import sys
import syslog
import struct
import time
from urllib.parse import urlencode

STATE = Path('/opt/dashplay/state')
RUNTIME = Path('/run/dashplay')
RECEIVER = Path('/var/run/dashplay')
LINK = Path('/sys/class/net/iphonewan0')
LAST = RUNTIME / 'n1-last-wired'
MARKER = RUNTIME / 'usb-tether'

def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''

def wired():
    try:
        return json.loads(read(RECEIVER / 'wired-status.json')).get('phase') == 'live'
    except ValueError:
        return False

def phone_offers_internet(phone):
    # Same vendor request and carrier byte layout as the N1 kernel's ipheth driver.
    bridge = runpy.run_path('/opt/dashplay/iphone-usb-bridge.py')
    fd = os.open(bridge['node'](phone), os.O_RDWR)
    try:
        buf = ctypes.create_string_buffer(64)
        request = struct.pack(bridge['CONTROL_STRUCT'], 0xc0, 0x45, 0, 2, len(buf), 1000, ctypes.addressof(buf))
        length = fcntl.ioctl(fd, bridge['USBDEVFS_CONTROL'], bytearray(request))
        return (length == 1 and buf.raw[0] == 4) or (length >= 2 and buf.raw[1] == 4)
    finally:
        os.close(fd)

def receiver_api(path, body=None):
    # Pin a locally installed receiver certificate BEFORE sending its bearer token.
    # The connection stays on loopback, also for boxes using a private CA or a custom port.
    port = json.loads((STATE / 'receiver/config.json').read_text())['httpPort']
    certs = []
    for file in (STATE / 'tls/own/fullchain.pem', STATE / 'tls/leaf.crt'):
        pem = read(file)
        if '-----END CERTIFICATE-----' in pem:
            certs.append(ssl.PEM_cert_to_DER_cert(pem.split('-----END CERTIFICATE-----')[0] + '-----END CERTIFICATE-----'))
    if not certs:
        return {}
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(('127.0.0.1', int(port)), timeout=3) as raw, ctx.wrap_socket(raw) as tls:
        if tls.getpeercert(binary_form=True) not in certs:
            return {}
        client = http.client.HTTPConnection('127.0.0.1', int(port), timeout=3)
        client.sock = tls
        query = urlencode({'token': (STATE / 'receiver/browser-token').read_text().strip()})
        client.request('GET' if body is None else 'POST', path+'?'+query,
                       None if body is None else json.dumps(body), {'Content-Type':'application/json'})
        res = client.getresponse()
        return json.loads(res.read(32768)) if res.status == 200 else {}

def watch(index):
    phone = (LINK / 'device').resolve().parent
    serial = read(phone / 'serial')
    if not serial or read(phone / 'idVendor') != '05ac':
        return
    key = hashlib.sha256(serial.encode()).hexdigest()
    started = time.monotonic()
    attempted = False
    while time.monotonic() - started < 120 and read(LINK / 'ifindex') == index and MARKER.exists():
        carrier = read(LINK / 'carrier') == '1'
        if carrier and wired():
            tmp = LAST.with_suffix('.'+index)
            tmp.write_text(key)
            os.replace(tmp, LAST)
            return
        if read(RECEIVER / 'cable-carplay-off') == 'once' and time.monotonic() - started >= 15:
            if carrier or attempted or read(LAST) != key:
                return
            if phone_offers_internet(phone):
                rows = receiver_api('/api/phones')
                phones = rows.get('phones', [])
                if rows.get('wired') == 'available' and len(phones) == 1 and phones[0].get('active'):
                    if (read(LINK / 'ifindex') == index and read(LINK / 'carrier') == '0'
                            and read(RECEIVER / 'cable-carplay-off') == 'once'):
                        attempted = True
                        ok = receiver_api('/api/phones/switch', {'cable': True}).get('ok')
                        syslog.syslog('n1-iphone-usb: wired recovery ' + ('requested' if ok else 'not accepted'))
        time.sleep(2)

if __name__ == '__main__':
    os.umask(0o077)
    index = sys.argv[1]
    if index.isdigit() and MARKER.exists():
        # One worker per attachment, even when a boot scan and a net event overlap.
        with (RUNTIME / ('n1-usb-watch-'+index)).open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                watch(index)
            except BlockingIOError:
                pass
            except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as error:
                syslog.syslog('n1-iphone-usb: recovery check stopped ('+type(error).__name__+')')
