"""Exercise the dispatch/rollback contract in a temporary fixture (no module insertion)."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    # Only calls/inputs are substituted; keep the production case patterns and comparison.
    def put(name, text, mode=0o755):
        f=root/name; f.parent.mkdir(parents=True,exist_ok=True); f.write_text(text); f.chmod(mode); return f
    put('bin/uname','#!/bin/sh\necho "${KERNEL_FAKE:-6.12.115-ophub}"\n')
    put('bin/sha256sum','#!/bin/sh\nexec shasum -a 256 "$@"\n') if sys.platform == 'darwin' else None
    put('base/original','#!/bin/sh\nexit 42\n')
    put('kmod','#!/bin/sh\nexit 1\n')
    for key in ['boot','full']:
        put('base/'+key+'.absent','probe\n')
        put('base/'+key+'.sh','#!/bin/sh\nexit "${PLAN_FAILURE:-0}"\n')
        put(key+'/10-test','tun\n',0o644)
    put('modules.conf','',0o644); put('index','fixture',0o644)
    def fingerprint(key):
        inputs=[root/key/'10-test',root/'modules.conf',root/'index']
        b=b''.join((hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f)+'\n').encode() for f in inputs)
        return hashlib.sha256(b).hexdigest()+'\n'
    for key in ['boot','full']: put('base/'+key+'.sha256',fingerprint(key),0o644)
    src=Path(sys.argv[1]).read_text().replace('@KERNEL@','6.12.115-ophub').replace('/usr/libexec/n1-fast-kmods',str(root/'base')).replace('/sbin/kmod ]',str(root/'kmod')+' ]').replace('folder=/etc/modules-boot.d','folder='+str(root/'boot')).replace('folder=/etc/modules.d','folder='+str(root/'full')).replace('/etc/modules.conf',str(root/'modules.conf')).replace('/lib/modules/6.12.115-ophub/modules.dep.bin',str(root/'index')).replace('/lib/modules/6.12.115-ophub/$name.ko',str(root/'mods')+'/$name.ko')
    wrapper=put('loader',src)
    def check(args, rc, **env):
        r=subprocess.run([wrapper,*args],env={**os.environ,'PATH':str(root/'bin')+':'+os.environ['PATH'],**env})
        assert r.returncode==rc,(args,r.returncode,rc)
    check([],0); check(['/etc/modules.d/'],0)
    check(['/etc/modules-boot.d/'],0); check(['//etc/modules-boot.d/'],0)
    check(['/unrecognized'],42); check([],42,KERNEL_FAKE='future-kernel')
    check([],42,PLAN_FAILURE='1')
    probe=put('mods/probe.ko','fixture'); check([],42); probe.unlink()
    put('boot/11-new','rfcomm\n'); check(['/etc/modules-boot.d/'],42)
    put('index','changed'); check([],42)
print('Ten indexed boot/rollback checks passed; no modules loaded.')
