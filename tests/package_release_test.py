"""Exercise the release CLI with isolated packages, never player resources."""
from pathlib import Path
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
TITLE = 'December When There Is No Angel'
SHELL_FILES = (
    'sce_sys/icon0.png',
    'sce_sys/pic0.png',
    'sce_sys/livearea/contents/background.png',
    'sce_sys/livearea/contents/startup.png',
    'sce_sys/livearea/contents/template.xml',
    'sce_sys/manual/001.png',
)


def sfo_fixture(title=TITLE, title_id='TNSH00001', version='00.27'):
    """Real PSF layout with UTF-8 string entries, aligned data and NUL terminators."""
    keys = bytearray()
    values = bytearray()
    entries = bytearray()
    for key, text in [('TITLE', title), ('TITLE_ID', title_id), ('APP_VER', version)]:
        value = text.encode('utf-8') + b'\0'
        capacity = (len(value) + 3) & ~3
        entries.extend(struct.pack('<HHIII', len(keys), 0x0204, len(value), capacity, len(values)))
        keys.extend(key.encode('ascii') + b'\0')
        values.extend(value + b'\0' * (capacity - len(value)))
    key_start = 20 + len(entries)
    data_start = (key_start + len(keys) + 3) & ~3
    return (struct.pack('<4sIIII', b'\0PSF', 0x101, key_start, data_start, 3)
            + entries + keys + b'\0' * (data_start - key_start - len(keys)) + values)


class PackageReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='tenshi-package-test-')
        cls.root = Path(cls.temp.name)
        # Copy only release inputs. Never copy .git, tools caches or realease/data.
        for directory in ('src', 'tests', 'tools', 'vita_asset_pipeline', 'licenses', 'third_party', 'sce_sys', 'prepare', 'assets'):
            shutil.copytree(ROOT / directory, cls.root / directory,
                            ignore=shutil.ignore_patterns('__pycache__', 'bin', 'obj', 'opening.mp4', 'opening.idx'))
        for path in ROOT.iterdir():
            if path.is_file():
                shutil.copy2(path, cls.root / path.name)
        cls.dist = cls.root / 'dist'
        cls.dist.mkdir()
        # Building the program must not require any opening MP4 or packet index.
        # Windows Git may check out this pinned text file as CRLF. Restore its
        # official LF bytes only inside the fixture; leave the real license alone.
        license_path = cls.root / 'licenses/SourceHanSans-OFL.txt'
        license_path.write_bytes(license_path.read_bytes().replace(b'\r\n', b'\n'))
        # Isolate metadata tests from the supplied icon's tRNS transparency,
        # which the existing release policy rejects. No real artwork is edited.
        def chunk(kind, payload):
            return (struct.pack('>I', len(payload)) + kind + payload
                    + struct.pack('>I', zlib.crc32(kind + payload)))
        opaque_icon = (b'\x89PNG\r\n\x1a\n'
                       + chunk(b'IHDR', struct.pack('>IIBBBBB', 128, 128, 8, 3, 0, 0, 0))
                       + chunk(b'PLTE', b'\x00\x00\x00')
                       + chunk(b'IDAT', zlib.compress(b'\x00' * (129 * 128)))
                       + chunk(b'IEND', b''))
        (cls.root / 'sce_sys/icon0.png').write_bytes(opaque_icon)
        cls.entries = {name: (cls.root / name).read_bytes() for name in SHELL_FILES}
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'FONT_LICENSE.md',
                     'assets/SourceHanSansCN-Regular.otf', 'assets/source-han-sans.json',
                     'assets/opening.json',
                     'licenses/SourceHanSans-OFL.txt'):
            cls.entries[name] = (cls.root / name).read_bytes()
        cls.entries['eboot.bin'] = b'SCE\0fixture-not-an-executable'
        for path in (cls.root / 'licenses').iterdir():
            if path.is_file():
                cls.entries['licenses/' + path.name] = path.read_bytes()
        cls.entries['sce_sys/param.sfo'] = sfo_fixture()

    def test_validation_does_not_create_markdown_files(self):
        before = {p.relative_to(self.root) for p in self.root.rglob('*.md')}
        result = self.run_release(self.entries)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p.relative_to(self.root) for p in self.root.rglob('*.md')}, before)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_release(self, entries):
        with zipfile.ZipFile(self.dist / 'tenshi-vita.vpk', 'w') as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return subprocess.run([sys.executable, str(self.root / 'tools/package-release.py'),
                               '--output', str(self.dist), '--source-archive'],
                              cwd=self.root, capture_output=True, text=True, encoding='utf-8')

    def test_complete_package_preserves_shell_files_in_source_release(self):
        result = self.run_release(self.entries)
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.dist / 'tenshi-vita-source.zip') as archive:
            for name in SHELL_FILES:
                self.assertEqual(archive.read(name), self.entries[name])
            self.assertIn('assets/SourceHanSansCN-Regular.otf', archive.namelist())
            self.assertEqual(archive.read('assets/SourceHanSansCN-Regular.otf'),
                             self.entries['assets/SourceHanSansCN-Regular.otf'])

    def test_source_archive_excludes_misplaced_original_game_files(self):
        unwanted = self.root / 'src/voice.a'
        unwanted.write_bytes(b'commercial-resource-fixture')
        try:
            result = self.run_release(self.entries)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(self.dist / 'tenshi-vita-source.zip') as archive:
                self.assertNotIn('src/voice.a', archive.namelist())
        finally:
            unwanted.unlink()

    def test_default_validator_uses_metadata_from_the_published_data_pack(self):
        metadata = self.dist / 'data/opening.json'
        metadata.parent.mkdir(exist_ok=True)
        metadata.write_bytes(b'{"generatedMetadata":true}\n')
        entries = {**self.entries, 'assets/opening.json': metadata.read_bytes()}
        try:
            result = self.run_release(entries)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            metadata.unlink()

    def test_matching_but_invalid_shell_format_is_rejected(self):
        for name in ('sce_sys/pic0.png', 'sce_sys/livearea/contents/template.xml'):
            path = self.root / name
            original = path.read_bytes()
            try:
                path.write_bytes(b'not-a-valid-shell-format')
                result = self.run_release({**self.entries, name: path.read_bytes()})
                self.assertNotEqual(result.returncode, 0, 'Accepted invalid shell format: ' + name)
                self.assertIn(name, result.stderr)
            finally:
                path.write_bytes(original)

    def test_missing_shell_resource_is_rejected(self):
        for name in SHELL_FILES:
            with self.subTest(name=name):
                entries = dict(self.entries)
                del entries[name]
                result = self.run_release(entries)
                self.assertNotEqual(result.returncode, 0, 'Accepted missing resource: ' + name)
                self.assertIn(name, result.stderr)

    def test_stale_shell_resource_is_rejected(self):
        for name in SHELL_FILES:
            with self.subTest(name=name):
                entries = dict(self.entries)
                entries[name] += b'stale'
                result = self.run_release(entries)
                self.assertNotEqual(result.returncode, 0, 'Accepted stale resource: ' + name)
                self.assertIn(name, result.stderr)

    def test_old_application_title_is_rejected(self):
        entries = dict(self.entries)
        entries['sce_sys/param.sfo'] = sfo_fixture(title='Tenshi Vita')
        result = self.run_release(entries)
        self.assertNotEqual(result.returncode, 0, 'Accepted old application title')
        self.assertIn('TITLE', result.stderr)

    def test_game_video_is_rejected_in_program_vpk(self):
        for name in ('assets/opening.mp4', 'assets/opening.idx', 'data/music.a',
                     'unexpected.dat', 'libshacccg.suprx'):
            with self.subTest(name=name):
                entries = dict(self.entries)
                entries[name] = b'player-data'
                result = self.run_release(entries)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)

    def test_changed_identity_or_version_is_rejected(self):
        for field, sfo in [('TITLE_ID', sfo_fixture(title_id='OTHER0001')),
                           ('APP_VER', sfo_fixture(version='00.26'))]:
            with self.subTest(field=field):
                entries = dict(self.entries)
                entries['sce_sys/param.sfo'] = sfo
                result = self.run_release(entries)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(field, result.stderr)

    def test_malformed_sfo_with_embedded_version_is_rejected(self):
        entries = dict(self.entries)
        entries['sce_sys/param.sfo'] = b'invalid SFO with 00.27\0 embedded'
        result = self.run_release(entries)
        self.assertNotEqual(result.returncode, 0, 'Accepted invalid SFO')
        self.assertIn('SFO', result.stderr)


if __name__ == '__main__':
    unittest.main()
