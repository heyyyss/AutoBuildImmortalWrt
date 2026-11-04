"""Use real target UCI through verify-image.sh's QEMU wrapper; touch copies only."""
import importlib.machinery
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

mod = importlib.machinery.SourceFileLoader('n1_mode',sys.argv[1]).load_module()
mod.STATE=Path(sys.argv[2])/'state.json'
def u(*args):
    return subprocess.check_output(['uci',*args],text=True).strip()
def apply(on):
    mod.dirty.clear()
    mod.reconcile(on, live=False)
def baseline():
    return [sorted(u('-X','show',p).splitlines()) for p in ('network','dhcp','wireless','firewall','uhttpd')]
Path(os.environ['N1_UCI_CONFIG'],'wireless').touch(exist_ok=True)
for assignment in ['wireless.radio0=wifi-device','wireless.radio0.type=mac80211','wireless.radio0.disabled=1',
                   'wireless.radio0.channel=auto','wireless.home=wifi-iface','wireless.home.device=radio0',
                   'wireless.home.network=lan','wireless.home.disabled=0',
                   'dashplay.main.wifi=n1_car','dashplay.main.viewer_port=443']:
    u('set',assignment)
u('commit')
before=baseline()
key=mac=None
for _ in range(2):
    apply(True)
    assert u('get','network.lan.device')=='eth0' and u('get','network.lan.proto')=='dhcp'
    assert u('get','dhcp.lan.ignore')=='1' and u('get','dhcp.lan.ra')=='disabled'
    assert u('get','network.carplay.ipaddr')=='100.96.0.1'
    assert u('get','wireless.home.disabled')=='1' and u('get','wireless.n1_car.network')=='carplay'
    assert u('get','firewall.n1_usb.device')=='dpncm' and u('get','firewall.n1_usb.forward')=='REJECT'
    assert u('get','firewall.n1_uplink.src')=='carplay' and u('get','firewall.n1_nat.src_ip')=='100.96.0.0/24'
    for http in mod.sections('uhttpd','uhttpd'):
        assert not any(v.endswith(':443') for v in (mod.get(http+'.listen_https') or '').splitlines())
    shutil.copyfile(Path(os.environ["N1_UCI_CONFIG"],"firewall"),Path(sys.argv[2])/"firewall-on")
    on=baseline()
    apply(True)
    assert on==baseline()
    st=json.loads(mod.STATE.read_text())
    assert len(st['key'])>=16 and st['mac'].startswith('02:')
    if key: assert key==st['key'] and mac==st['mac']
    key,mac=st['key'],st['mac']
    apply(False)
    shutil.copyfile(Path(os.environ["N1_UCI_CONFIG"],"firewall"),Path(sys.argv[2])/"firewall-off")
    assert before==baseline(), 'off did not restore original UCI'
    apply(False)
    assert before==baseline()
print('Two router → car → router cycles: Ethernet/DHCP/RA unchanged, AP/USB/443 removed, previous Wi-Fi and LuCI listeners restored.')
