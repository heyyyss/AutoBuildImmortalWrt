"""Apply the N1 viewer changes to the release bundle before building its APK."""
import sys
from pathlib import Path

def edit(root, file, old, new):
    p = root / file
    s = p.read_text()
    if s.count(old) != 1:
        raise ValueError(f"{file}: expected exactly one {old!r}; review new upstream source")
    p.write_text(s.replace(old, new))

if __name__ == '__main__':
    root = Path(sys.argv[1])
    edit(root, 'viewer_port.py', 'RESERVED = (80, 443, 7000)', 'RESERVED = (80, 7000)')
    edit(root, 'viewer_port.py', 'return 1024 <= port <= 65535 and port not in RESERVED',
         'return port == 443 or (1024 <= port <= 65535 and port not in RESERVED)')
    edit(root, 'run-receiver.py', 'import audio_routes\n', 'import audio_routes\nimport viewer_port\n')
    edit(root, 'run-receiver.py', 'if 1024 <= args.viewer_port <= 65535 else 0', 'if viewer_port.valid(args.viewer_port) else 0')
    edit(root, 'settings_page.py', 'name=viewer_port min=1024 ', 'name=viewer_port min=443 ')
    edit(root, 'settings_page.py', '端口要在 1024–65535 之间，且不能是', '可选 443 或 1024–65535 范围内的端口，需避开')

    edit(root, 'update.py', 'def launch(root, openwrt=None, version=None):',
         'def launch(root, openwrt=None, version=None):\n    raise RuntimeError("N1: install the matching DashPlay APK from your firmware build.")')
    edit(root, 'update.py', 'def install(root, openwrt=None, key=KEY, version=None):',
         'def install(root, openwrt=None, key=KEY, version=None):\n    raise RuntimeError("N1: install the matching DashPlay APK from your firmware build.")')
