"""Exercise CI publication with real VPK validation and no original game data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import package_release_test as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class CiBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PackageReleaseTest.setUpClass()
        cls.project = fixtures.PackageReleaseTest.root
        workflow = cls.project / '.github/workflows/vita.yml'
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text('name: fixture\non: push\n', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        fixtures.PackageReleaseTest.tearDownClass()

    def load_ci(self):
        path = ROOT / 'tools/build-ci.py'
        self.assertTrue(path.is_file(), 'Missing program-only CI build entrypoint')
        spec = importlib.util.spec_from_file_location('tenshi_ci_build', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def package(self, directory, extra=None):
        path = directory / 'input.vpk'
        entries = {**fixtures.PackageReleaseTest.entries, **(extra or {})}
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return path

    def test_program_only_publication_produces_exact_download_files_and_valid_checksums(self):
        ci = self.load_ci()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            vpk = self.package(directory)
            output = directory / 'artifacts'
            before = {p.relative_to(self.project) for p in self.project.rglob('*.md')}
            ci.publish_ci(self.project, vpk, output, {'compiler': 'fixture compiler'})
            self.assertEqual({p.name for p in output.iterdir()}, {
                'tenshi-vita.vpk', 'tenshi-vita-source.zip', 'build-report.json', 'SHA256SUMS.txt'})
            self.assertEqual((output / 'tenshi-vita.vpk').read_bytes(), vpk.read_bytes())
            report = json.loads((output / 'build-report.json').read_text())
            self.assertTrue(report['externalDataRequired'])
            self.assertFalse(report['package']['gameArchivesBundled'])
            self.assertEqual(report['build']['compiler'], 'fixture compiler')
            lines = (output / 'SHA256SUMS.txt').read_text().splitlines()
            self.assertEqual(len(lines), 3)
            for line in lines:
                digest, name = line.split('  ')
                self.assertEqual(digest, hashlib.sha256((output / name).read_bytes()).hexdigest())
            self.assertEqual({p.relative_to(self.project) for p in self.project.rglob('*.md')}, before)
            with zipfile.ZipFile(output / 'tenshi-vita-source.zip') as source:
                self.assertIn('.github/workflows/vita.yml', source.namelist())
                self.assertFalse(any(name.endswith(('.a', '.v', '.mp4', '.idx'))
                                     for name in source.namelist()))

    def test_game_data_in_vpk_prevents_any_download_publication(self):
        ci = self.load_ci()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            vpk = self.package(directory, {'data/music.a': b'game data'})
            output = directory / 'artifacts'
            with self.assertRaisesRegex(ValueError, 'Player asset'):
                ci.publish_ci(self.project, vpk, output, {})
            self.assertFalse(output.exists())

    def test_existing_outputs_are_neither_overwritten_nor_bundled(self):
        ci = self.load_ci()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = directory / 'artifacts'
            output.mkdir()
            sentinel = output / 'voice.a'
            sentinel.write_bytes(b'keep user data')
            with self.assertRaisesRegex(ValueError, 'empty'):
                ci.publish_ci(self.project, self.package(directory), output, {})
            self.assertEqual(sentinel.read_bytes(), b'keep user data')
            self.assertEqual(list(output.iterdir()), [sentinel])

    def test_output_cannot_replace_project_sources_or_local_player_release(self):
        ci = self.load_ci()
        with tempfile.TemporaryDirectory() as temporary:
            vpk = self.package(Path(temporary))
            for output in (self.project, self.project / 'src/ci-output',
                           self.project / 'realease/ci-output', self.project.parent):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    ci.publish_ci(self.project, vpk, output, {})

    def test_symlink_to_project_sources_is_not_an_output(self):
        ci = self.load_ci()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            link = directory / 'redirect'
            try:
                link.symlink_to(self.project / 'src', target_is_directory=True)
            except OSError:
                self.skipTest('Creating symlinks requires platform privileges')
            vpk = self.package(directory)
            for output in (link, link / 'ci-output'):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    ci.publish_ci(self.project, vpk, output, {})

    def test_cli_rejects_nonempty_output_before_sdk_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            sentinel = output / 'voice.a'
            sentinel.write_bytes(b'keep')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/build-ci.py'),
                                     '--sdk', '/not/an/installed/sdk', '--output', str(output)],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('empty', result.stderr)
            self.assertEqual(list(output.iterdir()), [sentinel])

    def test_cli_rejects_invalid_jobs_without_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'output'
            result = subprocess.run([sys.executable, str(ROOT / 'tools/build-ci.py'),
                                     '--jobs', '0', '--output', str(output)],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--jobs', result.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
