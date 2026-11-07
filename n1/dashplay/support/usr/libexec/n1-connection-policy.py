#!/usr/bin/python3
"""N1 automatic transport selection: keep a live session, recover an idle one."""
from dataclasses import dataclass
from pathlib import Path
import fcntl
import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import syslog
import time
from urllib.parse import urlencode

STATE = Path('/opt/dashplay/state')
RUN = Path('/var/run/dashplay')
STATUS = Path('/run/dashplay/n1-connection-policy.json')
HOLD = RUN/'cable-carplay-off'
POLL = 2.0

def read(p):
    try: return Path(p).read_text().strip()
    except OSError: return ''

def api(path, body=None):
    # Authenticate the local TLS endpoint before sending its private viewer token.
    port = int(json.loads((STATE/'receiver/config.json').read_text())['httpPort'])
    certs = []
    for p in [STATE/'tls/own/fullchain.pem', STATE/'tls/leaf.crt']:
        pem=read(p)
        if '-----END CERTIFICATE-----' in pem:
            certs.append(ssl.PEM_cert_to_DER_cert(pem.split('-----END CERTIFICATE-----')[0]+'-----END CERTIFICATE-----'))
    if not certs: raise RuntimeError('no trusted local certificate')
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
    with socket.create_connection(('127.0.0.1',port),timeout=3) as raw,ctx.wrap_socket(raw) as tls:
        if tls.getpeercert(binary_form=True) not in certs: raise RuntimeError('local certificate mismatch')
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=3);c.sock=tls
        token=read(STATE/'receiver/browser-token')
        if not token: raise RuntimeError('receiver token not ready')
        c.request('GET' if body is None else 'POST',path+'?'+urlencode({'token':token}),
                  None if body is None else json.dumps(body),{'Content-Type':'application/json'})
        r=c.getresponse();data=r.read(32768)
        if r.status!=200: raise RuntimeError('receiver API not ready')
        return json.loads(data)

def usb_present():
    for p in Path('/sys/bus/usb/devices').glob('*'):
        if ':' not in p.name and read(p/'idVendor')=='05ac' and read(p/'serial'):
            return True
    return False

def wifi_present(address):
    """An AP association is availability, never proof that CarPlay is healthy."""
    try:
        data=json.loads((STATE/'receiver/phone-presence.json').read_text())
        macs={re.sub('[^0-9a-f]','',x.get('mac','').lower()) for x in data['phones'][address]['networks'].values()}
        macs={m for m in macs if len(m)==12}
        if not macs:return None
        r=subprocess.run(['iw','dev'],capture_output=True,text=True,timeout=3)
        if r.returncode:return None
        interfaces=[b.splitlines()[0].strip() for b in r.stdout.split('Interface ')[1:] if re.search(r'\btype AP\b',b)]
        if not interfaces:return None
        for interface in interfaces:
            r=subprocess.run(['iw','dev',interface,'station','dump'],capture_output=True,text=True,timeout=3)
            if r.returncode:return None
            if any(m.replace(':','').lower() in macs for m in re.findall(r'^Station ([0-9a-f:]+)',r.stdout,re.M)):
                return True
        return False
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired):
        return None

@dataclass
class Observation:
    active: str | None
    usb: bool
    wifi: bool | None
    allowed_usb: bool = True
    automatic: bool = True
    display_changed: bool = False
    native_progress: bool = False

@dataclass
class Action:
    target: str
    reason: str

class Policy:
    """Pure transition policy. The receiver retains ownership of transport setup."""
    def __init__(self):
        self.last_good=None
        self.lost_at=None
        self.display_until=0
        self.pending=None
        self.pending_until=0
        self.next_try={'wired':0,'wireless':0}
        self.failures={'wired':0,'wireless':0}
        self.last_attempt=None
        self.previous_ready=set()
        self.ready_since={}
        self.phase='waiting_receiver'

    def observe(self,o,now):
        if o.display_changed:self.display_until=now+30
        ready=set()
        if o.usb and o.allowed_usb:ready.add('wired')
        if o.wifi is True:ready.add('wireless')
        restored=ready-self.previous_ready
        self.previous_ready=ready
        for target in restored:self.ready_since[target]=now
        for target in list(self.ready_since):
            if target not in ready:del self.ready_since[target]
        if o.active:
            # Availability, including USB internet failure, never displaces a live session.
            self.last_good=o.active;self.lost_at=None;self.pending=None
            self.failures={'wired':0,'wireless':0}
            self.next_try={'wired':0,'wireless':0}
            self.last_attempt=None;self.phase='healthy_'+o.active
            return None
        if not o.automatic:
            self.pending=None;self.lost_at=None;self.phase='manual_selection_required'
            return None
        if self.lost_at is None:self.lost_at=now
        if not ready:
            self.pending=None;self.phase='waiting_link'
            return None
        for target in restored:
            self.next_try[target]=0
            self.failures[target]=0
        # A disappearing physical link overrides the display-change grace.
        physical_loss=(self.last_good=='wired' and not o.usb) or (self.last_good=='wireless' and o.wifi is False)
        if now<self.display_until and not physical_loss:
            self.phase='waiting_display_reconnect'
            return None
        if now-self.lost_at<4:
            self.phase='confirming_disconnect'
            return None
        if self.pending:
            if self.pending in ready and now<self.pending_until:
                self.phase='connecting_'+self.pending
                return None
            self.rejected(now)
        eligible={target for target in ready if now>=self.next_try[target]}
        # The receiver already invites wireless on unplug/return. Let that complete
        # before issuing a second invitation, which would close a just-opened session.
        if 'wireless' in eligible and (o.native_progress or now-self.ready_since['wireless']<20):
            eligible.remove('wireless')
            if not eligible:
                self.phase='waiting_native_wireless'
                return None
        if not eligible:
            self.phase='retry_backoff'
            return None
        # After loss, prefer the other usable path; with no previous session use USB if present.
        alternate='wireless' if self.last_good=='wired' else 'wired'
        # If one handshake failed, try the other link before repeating the same attempt.
        if self.last_attempt:
            alternate='wireless' if self.last_attempt=='wired' else 'wired'
        target=alternate if alternate in eligible else ('wired' if 'wired' in eligible else 'wireless')
        self.pending=target
        self.last_attempt=target
        self.pending_until=now+(35 if target=='wireless' else 30)
        self.phase='connecting_'+target
        return Action(target,'recover_'+(self.last_good or 'idle'))

    def rejected(self,now):
        target=self.pending
        if target:
            self.failures[target]+=1
            self.next_try[target]=now+min(60,10*2**min(self.failures[target]-1,3))
        self.pending=None
        self.phase='retry_backoff'

class DisplayEvents:
    def __init__(self):
        self.file=RUN/'receiver.log';self.identity=None;self.offset=0
        self.native_until=0
        try:
            s=self.file.stat();self.identity=(s.st_dev,s.st_ino);self.offset=s.st_size
        except OSError:pass
    def changed(self):
        try:
            st=self.file.stat();identity=(st.st_dev,st.st_ino)
            if identity!=self.identity or st.st_size<self.offset:self.offset=0
            self.identity=identity
            start=max(self.offset,st.st_size-131072)
            with self.file.open('rb') as f:f.seek(start);data=f.read()
            self.offset=st.st_size
            if any(marker in data for marker in [b'AirPlay connection accepted from ', b'CarPlay session active peer=', b'wireless iAP2 tunnel ready; CarPlay is live']):
                self.native_until=time.monotonic()+12
            return b'display changed to ' in data and b'restarting CarPlay' in data
        except OSError:return False

def snapshot(events):
    rows=api('/api/phones')
    phones=rows.get('phones',[])
    usb=usb_present()
    active='wired' if rows.get('wired')=='live' and usb else ('wireless' if any(p.get('active') for p in phones) else None)
    # Avoid active Wi-Fi scans; station status is read only while no session is live.
    wifi=None if active else (wifi_present(phones[0]['address']) if len(phones)==1 else None)
    allowed=read(HOLD)!='static'
    changed=events.changed()
    return Observation(active,usb,wifi,allowed,len(phones)<=1,changed,time.monotonic()<events.native_until),phones

def event(kind,**values):
    row={'uptime':round(time.monotonic(),3),'event':kind,**values}
    line=json.dumps(row,separators=(',',':'))
    syslog.syslog('n1-connection-policy '+line)
    RUN.mkdir(parents=True,exist_ok=True)
    path=RUN/'connection-policy.log'
    if path.exists() and path.stat().st_size>262144:
        path.replace(path.with_suffix('.log.1'))
    with path.open('a') as f:f.write(line+'\n')

def perform(action,policy,events=None):
    # Recheck immediately before mutation; a late successful handshake always wins.
    latest=api('/api/phones')
    if latest.get('wired')=='live' or any(p.get('active') for p in latest.get('phones',[])):
        policy.pending=None
        return
    phones=latest.get('phones',[])
    if len(phones)>1:
        policy.rejected(time.monotonic())
        return
    if action.target=='wired':
        if not usb_present() or read(HOLD)=='static':
            policy.rejected(time.monotonic())
            return
        body={'cable':True}
    else:
        if len(phones)!=1 or wifi_present(phones[0]['address']) is not True:
            policy.rejected(time.monotonic())
            return
        body={'address':phones[0]['address']}
        if events:
            events.changed()
            if time.monotonic()<events.native_until:
                policy.pending=None
                return
    event('select',target=action.target,reason=action.reason)
    if not api('/api/phones/switch',body).get('ok'):
        policy.rejected(time.monotonic())

def main():
    os.umask(0o077)
    STATUS.parent.mkdir(parents=True,exist_ok=True)
    with (STATUS.parent/'n1-connection-policy.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        policy=Policy();events=DisplayEvents();previous=None
        while True:
            started=time.monotonic()
            try:
                o,phones=snapshot(events)
                action=policy.observe(o,time.monotonic())
                if action:
                    perform(action,policy,events)
                state={'phase':policy.phase,'active':o.active,'last_good':policy.last_good,
                       'usb_available':o.usb,'wifi_available':o.wifi,'pending':policy.pending,
                       'failed_attempts':policy.failures}
                if state!=previous:
                    event('state',**state);previous=state
                    temp=STATUS.with_suffix('.new')
                    temp.write_text(json.dumps({'checked_uptime':round(time.monotonic(),3),**state},indent=2)+'\n')
                    temp.replace(STATUS)
            except (OSError,ValueError,KeyError,TypeError,RuntimeError,http.client.HTTPException):
                if previous!='api_unavailable':
                    event('waiting_receiver')
                    previous='api_unavailable'
            time.sleep(max(0.2,POLL-(time.monotonic()-started)))

if __name__=='__main__':main()
