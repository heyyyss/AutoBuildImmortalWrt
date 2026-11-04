"""Generate guarded boot plans against THIS final ophub root and module index."""
import hashlib
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

def generate(root, kernel):
    base = root / 'usr/libexec/n1-fast-kmods'
    base.mkdir()
    modules = root / 'lib/modules' / kernel
    assert (modules / 'modules.dep.bin').stat().st_size > 0
    # Do not introduce a dependency on /usr/bin/python in preinit.
    shutil.copy2(root/'sbin/kmodloader', base/'original')
    for key, folder in [('boot','/etc/modules-boot.d'), ('full','/etc/modules.d')]:
        entries = sorted(p for p in (root/folder[1:]).iterdir() if p.is_file())
        inputs = entries + [root/'etc/modules.conf', modules/'modules.dep.bin']
        fingerprint = b''.join((hashlib.sha256(p.read_bytes()).hexdigest()+'  /'+str(p.relative_to(root))+'\n').encode() for p in inputs)
        (base/(key+'.sha256')).write_text(hashlib.sha256(fingerprint).hexdigest()+'\n')
        commands, batch = [], []
        def flush():
            if batch:
                commands.append(['-a',*batch])
                batch.clear()
        for p in entries:
            for line in p.read_text().splitlines():
                args=line.split('#',1)[0].split()
                if not args: continue
                if not re.fullmatch(r'[a-zA-Z0-9_-]+', args[0]): raise ValueError(line)
                r=subprocess.run(['modprobe','-d',str(root),'-S',kernel,'-n',*args], capture_output=True)
                if r.returncode:
                    if (modules/(args[0]+'.ko')).exists(): raise ValueError('index missing '+args[0])
                    continue
                if len(args)>1:
                    flush()
                    commands.append(args)
                else:
                    batch.append(args[0])
        flush()
        assert commands
        (base/(key+'.sh')).write_text('#!/bin/sh\nset -e\n' + ''.join('/sbin/modprobe "$@" '+shlex.join(c)+'\n' for c in commands))
    wrapper=(Path(__file__).with_name('fast-loader.sh')).read_text().replace('@KERNEL@',kernel)
    # Replace the file, never write through a packaged symlink.
    loader=root/'sbin/kmodloader'
    loader.unlink()
    loader.write_text(wrapper)
    loader.chmod(0o755)

if __name__ == '__main__':
    generate(Path(sys.argv[1]).resolve(),sys.argv[2])
