"""Deterministic patches for the pinned DashPlay 2026.11.02 viewer assets."""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WEB = Path('playport/web/dist')
MAIN = 'assets/main-bA1a8eYW.js'
LOADER = 'assets/index-CS3SioKU.js'
NEW_MAIN = 'main-n1-reconnect-20261107-r2.js'
NEW_LOADER = 'index-n1-reconnect-20261107-r2.js'


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Viewer anchor changed: {old[:80]!r}')
    return source.replace(old, new)


def check_hashes(root, expected):
    for name, digest in expected.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Viewer hash changed: {name}; review the pinned upstream bundle')


def render(root):
    """Prepare all outputs in memory before touching the bundle."""
    dist = root / WEB
    source = (dist / MAIN).read_text()
    for old, new in [
        # The main module imports timing exports from its loader. Leaving this
        # reference on the old loader also starts the old player as a side effect.
        ('from"./' + Path(LOADER).name + '";', 'from"./' + NEW_LOADER + '";'),
        ('function cr(e){', 'function cr(e){n1DisplayGate.session(e);'),
        ('async function Mr(e,t){if(Qt||!w)return!1;Qt=!0,',
         'async function Mr(e,t){if(Qt||!w)return!1;let n1Ticket=!t.defer&&(!k||!bt(k,e))?n1DisplayGate.begin(T):null;Qt=!0,'),
        ('return r.deferred?(k&&(k.pending=!0)',
         'return r.deferred?(n1DisplayGate.cancel(n1Ticket),k&&(k.pending=!0)'),
        ('catch{return n&&(jr(),L()),b(`display-status`).textContent=y(`applyFail`)',
         'catch{return n1DisplayGate.cancel(n1Ticket),n&&(jr(),L()),b(`display-status`).textContent=y(`applyFail`)'),
        ('finally{Qt=!1,b(`apply`).disabled=!1,b(`display-fields`).disabled=!1,N()}}function Q()',
         'finally{await n1DisplayGate.wait(n1Ticket);Qt=!1,b(`apply`).disabled=!1,b(`display-fields`).disabled=!1,N(),Q()}}function Q()'),
        ('Zt=window.setTimeout(()=>{Nr()},1500)', 'Zt=window.setTimeout(()=>{Nr()},2500)'),
    ]:
        source = replace_once(source, old, new)
    source = (HERE / 'web/display-gate.js').read_text() + '\n' + source
    loader = replace_once((dist / LOADER).read_text(), Path(MAIN).name, NEW_MAIN)
    html = replace_once((dist / 'index.html').read_text(), Path(LOADER).name, NEW_LOADER)
    # A classic, same-origin script runs before the module viewer creates audio contexts.
    # It affects only this optional page and never changes the receiver's audio settings.
    ipad = replace_once(html, '<head>', '<head>\n    <script src="./n1-ipad-audio.js"></script>')
    return {
        str(WEB / 'assets' / NEW_MAIN): source.encode(),
        str(WEB / 'assets' / NEW_LOADER): loader.encode(),
        str(WEB / 'index.html'): html.encode(),
        str(WEB / 'ipad-audio-test.html'): ipad.encode(),
        str(WEB / 'n1-ipad-audio.js'): (HERE / 'web/n1-ipad-audio.js').read_bytes(),
    }


def manifest():
    return json.loads((HERE / 'web/hashes.json').read_text())


def patch(root):
    hashes = manifest()
    check_hashes(root, hashes['upstream'])
    outputs = render(root)
    actual = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    if actual != hashes['patched']:
        raise ValueError('Viewer output changed; review the patch and update its expected hashes')
    for name, data in outputs.items():
        (root / name).write_bytes(data)
    verify(root)


def verify(root):
    hashes = manifest()
    # The official USB bridge remains unchanged; only the procd policy selects recovery.
    check_hashes(root, {k: v for k, v in hashes['upstream'].items() if k != str(WEB / 'index.html')})
    check_hashes(root, hashes['patched'])
    main = (root / WEB / 'assets' / NEW_MAIN).read_text()
    loader = (root / WEB / 'assets' / NEW_LOADER).read_text()
    if ('from"./' + NEW_LOADER + '";') not in main or Path(LOADER).name in main:
        raise ValueError('Viewer main must import only the renamed loader')
    if ('import(`./' + NEW_MAIN + '`)') not in loader or Path(MAIN).name in loader:
        raise ValueError('Viewer loader must initialize only the renamed main')
    if (root / 'n1_cable_fallback.py').exists():
        raise ValueError('Obsolete cable fallback must not be packaged')
    print('Pinned viewer hashes, display reconnect gate, independent iPad page and official USB bridge: OK')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--verify':
        verify(Path(sys.argv[2]))
    elif len(sys.argv) == 2:
        patch(Path(sys.argv[1]))
    else:
        raise SystemExit('usage: patch-viewer.py [--verify] BUNDLE_ROOT')
