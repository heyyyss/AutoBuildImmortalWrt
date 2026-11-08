"""Exercise the pinned patch on real bundle assets or the final installed image."""
import hashlib
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
patcher = runpy.run_path(str(HERE / 'patch-viewer.py'))
installed = sys.argv[1] == '--installed'
source = Path(sys.argv[2] if installed else sys.argv[1])
sys.argv = [sys.argv[0]]


class ViewerPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in patcher['manifest']()['upstream']:
            data = (source / name).read_bytes()
            if installed and name == str(patcher['WEB'] / 'index.html'):
                data = data.replace(patcher['NEW_LOADER'].encode(), Path(patcher['LOADER']).name.encode())
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def snapshot(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_outputs_and_optional_audio_page(self):
        patcher['patch'](self.root)
        patcher['verify'](self.root)
        dist = self.root / patcher['WEB']
        main = (dist / 'index.html').read_text()
        ipad = (dist / 'ipad-audio-test.html').read_text()
        self.assertNotIn('n1-ipad-audio.js', main)
        self.assertEqual(ipad.count('n1-ipad-audio.js'), 1)
        self.assertLess(ipad.index('n1-ipad-audio.js'), ipad.index(patcher['NEW_LOADER']))

    def test_rejects_changed_input_without_partial_writes(self):
        for name in patcher['manifest']()['upstream']:
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            before = self.snapshot()
            with self.assertRaises(ValueError):
                patcher['patch'](self.root)
            self.assertEqual(before, self.snapshot())
            path.write_bytes(original)

    def test_player_initializes_once(self):
        patcher['patch'](self.root)
        subprocess.run(['node', str(HERE / 'tests/viewer-module-load.mjs'),
                        str(self.root / patcher['WEB'])], check=True)

    def test_rejects_double_patch(self):
        patcher['patch'](self.root)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            patcher['patch'](self.root)
        self.assertEqual(before, self.snapshot())

    def test_rejects_missing_or_duplicate_anchor(self):
        for text in ['other content', 'anchor anchor']:
            with self.assertRaises(ValueError):
                patcher['replace_once'](text, 'anchor', 'replacement')

    def test_verification_rejects_stale_page(self):
        patcher['patch'](self.root)
        (self.root / patcher['WEB'] / 'index.html').write_text('old viewer')
        with self.assertRaises(ValueError):
            patcher['verify'](self.root)

    def test_verification_rejects_second_usb_policy(self):
        patcher['patch'](self.root)
        (self.root / 'n1_cable_fallback.py').write_text('# obsolete')
        with self.assertRaises(ValueError):
            patcher['verify'](self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
