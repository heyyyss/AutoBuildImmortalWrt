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
    assert u('get','network.iphone_usb.device')=='iphonewan0' and u('get','network.iphone_usb.proto')=='dhcp'
    assert u('get','network.iphone_usb.metric')=='70'
    assert u('get','firewall.n1_iphone_wan.network')=='iphone_usb' and u('get','firewall.n1_iphone_wan.masq')=='1'
    assert u('get','firewall.n1_car_to_iphone.src')=='carplay' and u('get','firewall.n1_car_to_iphone.dest')=='iphonewan'
    assert u('get','firewall.n1_iphone_wan.input')=='REJECT' and u('get','firewall.n1_iphone_wan.forward')=='REJECT'
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
u('set', 'network.iphone_usb=interface')
u('set', 'network.iphone_usb.device=other0')
u('commit', 'network')
try:
    apply(True)
except RuntimeError as error:
    assert 'network.iphone_usb' in str(error)
else:
    raise AssertionError('overwrote a foreign USB interface')
assert u('get', 'network.iphone_usb.device')=='other0'
u('delete', 'network.iphone_usb')
u('commit', 'network')
# Upgrade a build #3 that already has the hand-installed tether settings.
apply(True)
st=json.loads(mod.STATE.read_text())
del st['iphone_usb_owned']
mod.save(st)
apply(True)
assert json.loads(mod.STATE.read_text())['iphone_usb_owned']
apply(False)
assert before==baseline()
print('Router/car cycles, USB tether migration and collision handling passed; prior Wi-Fi, Ethernet, LuCI and firewall restored.')
