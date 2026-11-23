"""Exercise real staging: never replace the user's originals to make a VPK."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class VpkResourcesTest(unittest.TestCase):
    def test_transparent_icon_is_staged_opaque_and_originals_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'project'
            for directory in ('sce_sys', 'licenses', 'assets'):
                shutil.copytree(ROOT / directory, root / directory,
                                ignore=shutil.ignore_patterns('opening.mp4', 'opening.idx'))
            icon = root / 'sce_sys/icon0.png'
            image = Image.new('P', (128, 128), 1)
            image.putpalette([0, 0, 0, 20, 80, 120] + [0] * 762)
            image.putpixel((0, 0), 0)
            image.save(icon, transparency=0, bits=8)
            (root / 'sce_sys/param.sfo').write_bytes(b'stale-sfo')
            originals = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            output = Path(temporary) / 'build/vpk-resources'
            result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools/vpk_resources.py'),
                                     str(output), '--root', str(root)], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            for name, data in originals.items():
                self.assertEqual((root / name).read_bytes(), data, 'Original changed: ' + str(name))
            built_icon = (output / 'sce_sys/icon0.png').read_bytes()
            self.assertEqual(built_icon[16:26], bytes.fromhex('00000080000000800803'))
            with Image.open(output / 'sce_sys/icon0.png') as built:
                self.assertNotIn('transparency', built.info)
                self.assertEqual(built.convert('RGB').getpixel((64, 64)), (20, 80, 120))
            self.assertFalse((output / 'sce_sys/param.sfo').exists())
            self.assertEqual((output / 'sce_sys/manual/001.png').read_bytes(),
                             originals[Path('sce_sys/manual/001.png')])
            expected = json.loads((root / 'assets/source-han-sans.json').read_text())['licenseSha256']
            self.assertEqual(hashlib.sha256((output / 'licenses/SourceHanSans-OFL.txt').read_bytes()).hexdigest(), expected)

    def test_output_must_not_overlap_source_resources(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools/vpk_resources.py'), str(ROOT / 'sce_sys')],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('overlap', result.stderr)


if __name__ == '__main__':
    unittest.main()
