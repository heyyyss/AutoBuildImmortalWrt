"""Exercise replug policy without a real iPhone; real UCI/fw4 is tested separately."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import runpy

source = Path(__file__).resolve().parents[1] / 'support/usr/libexec/n1-iphone-usb-watch.py'
watch = runpy.run_path(str(source))['watch']

def simulate(role='once', carrier='0', remembered=True, devices=1, hotspot=True):
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        phone, link, receiver = base/'phone', base/'net', base/'receiver'
        for directory in (phone/'iface', link, receiver):
            directory.mkdir(parents=True)
        (link/'device').symlink_to(phone/'iface')
        (phone/'idVendor').write_text('05ac')
        (phone/'serial').write_text('fixture')
        (link/'ifindex').write_text('42')
        (link/'carrier').write_text(carrier)
        (receiver/'wired-status.json').write_text(json.dumps({'phase': 'live' if role == 'wired' else ''}))
        if role != 'wired':
            (receiver/'cable-carplay-off').write_text(role)
        last = base/'last'
        if remembered:
            last.write_text(hashlib.sha256(b'fixture').hexdigest())
        marker = base/'usb-tether'
        marker.touch()
        now, requests = [0], []
        def sleep(seconds):
            now[0] += seconds
        def api(path, body=None):
            if path == '/api/phones':
                return {'wired':'available', 'phones':[{'active':i == 0} for i in range(devices)]}
            assert path == '/api/phones/switch'
            requests.append(body)
            return {'ok':True}
        with patch.dict(watch.__globals__, LINK=link, RECEIVER=receiver, LAST=last, MARKER=marker,
                        time=Mock(monotonic=lambda:now[0], sleep=sleep), receiver_api=api,
                        phone_offers_internet=lambda phone:hotspot):
            watch('42')
        return requests, last.exists()

assert simulate()[0] == [{'cable':True}]
assert simulate(role='static')[0] == []
assert simulate(carrier='1')[0] == []
assert simulate(remembered=False)[0] == []
assert simulate(devices=2)[0] == []
assert simulate(hotspot=False)[0] == []
assert simulate(role='wired', carrier='1', remembered=False) == ([], True)
print('USB recovery selects a returning wired iPhone once and respects working tether, wireless-only and other phones.')
