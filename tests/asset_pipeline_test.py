"""Behavioral checks for the local asset cache and transactional publication."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class AssetPipelineTest(unittest.TestCase):
    def modules(self):
        # An absent feature is a useful RED assertion, not an import-time error.
        self.assertTrue((ROOT / 'vita_asset_pipeline/package.py').is_file(),
                        'The independent resource pipeline has not been implemented')
        from vita_asset_pipeline import package, common, release
        return package, common, release

    def fixture(self, temporary):
        project = Path(temporary) / 'project'
        source = Path(temporary) / 'original'
        (project / 'assets').mkdir(parents=True)
        source.mkdir()
        names = ('char.a', 'ed.a', 'egbg.a', 'music.a', 'se.a', 'sys.a', 'tenshi_dvd.a', 'voice.a')
        rows = []
        for name in (*names, 'openning.v'):
            data = ('original:' + name).encode()
            (source / name).write_bytes(data)
            rows.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (project / 'assets/game-data.json').write_text(json.dumps({'schema': 'tenshi-source-v1', 'files': rows}))
        (project / 'assets/opening.json').write_text(json.dumps({'sourceFile': 'openning.v',
            'sourceSha256': rows[-1]['sha256'], 'sourceBytes': rows[-1]['bytes'], 'conversion': ['-crf', '18']}))
        return project, source

    @staticmethod
    def converter(project, source, output, ffmpeg, ffprobe):
        # Encoding is the expensive external boundary. Cache/hash/copy/publication
        # logic is real; a separate integration run uses actual FFmpeg and SDK.
        (output / 'opening.mp4').write_bytes(b'converted-video')
        (output / 'opening.idx').write_bytes(b'packet-index')
        (output / 'opening.json').write_text('{"fixture":true}\n')

    def prepare(self, package, project, source):
        return package.prepare_data(project, source, project / '.work', 'ffmpeg', 'ffprobe',
                                    tool_versions={'ffmpeg': 'fixture-1', 'ffprobe': 'fixture-1'})

    def test_cache_is_reused_only_after_full_output_verification(self):
        package, _, _ = self.modules()
        with tempfile.TemporaryDirectory() as temp:
            project, source = self.fixture(temp)
            with patch.object(package, 'convert_opening', self.converter):
                first = self.prepare(package, project, source)
                self.assertFalse(first['cacheHit'])
                self.assertEqual((Path(first['data']) / 'char.a').read_bytes(), b'original:char.a')
                second = self.prepare(package, project, source)
                self.assertTrue(second['cacheHit'])
                self.assertEqual(first['key'], second['key'])
                (Path(second['data']) / 'voice.a').write_bytes(b'corrupted')
                third = self.prepare(package, project, source)
                self.assertFalse(third['cacheHit'])
                self.assertEqual((Path(third['data']) / 'voice.a').read_bytes(), b'original:voice.a')

    def test_conversion_settings_change_invalidates_cache(self):
        package, _, _ = self.modules()
        with tempfile.TemporaryDirectory() as temp:
            project, source = self.fixture(temp)
            with patch.object(package, 'convert_opening', self.converter):
                first = self.prepare(package, project, source)
                recipe = project / 'assets/opening.json'
                value = json.loads(recipe.read_text())
                value['conversion'] = ['-crf', '19']
                recipe.write_text(json.dumps(value))
                second = self.prepare(package, project, source)
                self.assertNotEqual(first['key'], second['key'])
                self.assertFalse(second['cacheHit'])

    def test_build_launcher_changes_do_not_reencode_unchanged_media(self):
        package, _, _ = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            project, source = self.fixture(temporary)
            module = project / 'vita_asset_pipeline/build.py'
            module.parent.mkdir()
            module.write_text('# first build launcher\n')
            with patch.object(package, 'convert_opening', self.converter):
                first = self.prepare(package, project, source)
                module.write_text('# updated build launcher\n')
                second = self.prepare(package, project, source)
            self.assertEqual(first['key'], second['key'])
            self.assertTrue(second['cacheHit'])

    def test_unlisted_cache_files_are_not_published_or_reused(self):
        package, _, _ = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            project, source = self.fixture(temporary)
            with patch.object(package, 'convert_opening', self.converter):
                first = self.prepare(package, project, source)
                (first['data'] / 'unexpected-private-file').write_bytes(b'not-a-game-input')
                second = self.prepare(package, project, source)
                self.assertFalse(second['cacheHit'])
                self.assertFalse((second['data'] / 'unexpected-private-file').exists())

    def test_cache_tool_version_change_requires_new_conversion(self):
        package, _, _ = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            project, source = self.fixture(temporary)
            with patch.object(package, 'convert_opening', self.converter):
                first = self.prepare(package, project, source)
                second = package.prepare_data(project, source, project / '.work', 'ffmpeg', 'ffprobe',
                                               tool_versions={'ffmpeg': 'fixture-2', 'ffprobe': 'fixture-1'})
                self.assertNotEqual(first['key'], second['key'])
                self.assertFalse(second['cacheHit'])

    def test_manifest_duplicate_file_is_rejected(self):
        _, common, _ = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'file'
            path.write_bytes(b'content')
            row = {'path': 'file', 'bytes': 7,
                   'sha256': 'ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec73f9'}
            with self.assertRaisesRegex(ValueError, 'Manifest'):
                common.verify_files(Path(temporary), [row, row])

    def test_bad_or_missing_original_is_rejected_even_with_a_cache(self):
        package, _, _ = self.modules()
        with tempfile.TemporaryDirectory() as temp:
            project, source = self.fixture(temp)
            with patch.object(package, 'convert_opening', self.converter):
                self.prepare(package, project, source)
                (source / 'music.a').write_bytes(b'wrong-version')
                with self.assertRaisesRegex(ValueError, 'music.a'):
                    self.prepare(package, project, source)
                (source / 'music.a').unlink()
                with self.assertRaisesRegex((ValueError, FileNotFoundError), 'music.a'):
                    self.prepare(package, project, source)

    def test_unsafe_manifest_paths_are_rejected(self):
        _, common, _ = self.modules()
        with tempfile.TemporaryDirectory() as temp:
            for name in ('../escape', '/absolute', 'C:/escape', 'a\\escape', '.', 'a/../escape'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    common.checked_path(Path(temp), name)

    def test_work_and_output_cannot_overlap_originals_or_source_tree(self):
        _, common, _ = self.modules()
        with tempfile.TemporaryDirectory() as temp:
            project, source = self.fixture(temp)
            for work, output in ((project, project / 'realease'),
                                 (project / '.work', source),
                                 (source / '.work', project / 'realease'),
                                 (project / '.work', project / 'assets'),
                                 (project / '.work', project / '.work/result')):
                with self.subTest(work=work, output=output), self.assertRaises(ValueError):
                    common.validate_locations(project, source, work, output)

    def test_failed_conversion_keeps_previous_release_untouched(self):
        package, _, _ = self.modules()
        with tempfile.TemporaryDirectory() as temp:
            project, source = self.fixture(temp)
            output = project / 'realease'
            output.mkdir()
            (output / 'tenshi-vita.vpk').write_bytes(b'previous-vpk')
            with patch.object(package, 'convert_opening', side_effect=RuntimeError('encoder failed')):
                with self.assertRaisesRegex(RuntimeError, 'encoder failed'):
                    self.prepare(package, project, source)
            self.assertEqual((output / 'tenshi-vita.vpk').read_bytes(), b'previous-vpk')

    def test_failed_directory_swap_rolls_back_and_keeps_staged_files(self):
        _, _, release = self.modules()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current, staged = root / 'realease', root / 'pending'
            current.mkdir(); staged.mkdir()
            (current / 'value').write_bytes(b'old')
            (staged / 'value').write_bytes(b'new')
            real_replace = release.os.replace

            def fail_commit(src, dst):
                if Path(src) == staged:
                    raise OSError('simulated publication failure')
                return real_replace(src, dst)

            with patch.object(release.os, 'replace', fail_commit):
                with self.assertRaisesRegex(OSError, 'publication failure'):
                    release.commit_directory(staged, current, root / 'backups')
            self.assertEqual((current / 'value').read_bytes(), b'old')
            self.assertEqual((staged / 'value').read_bytes(), b'new')

    def test_directory_swap_preserves_previous_output_as_backup(self):
        _, _, release = self.modules()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current, staged = root / 'realease', root / 'pending'
            current.mkdir(); staged.mkdir()
            (current / 'value').write_bytes(b'old')
            (staged / 'value').write_bytes(b'new')
            backup = release.commit_directory(staged, current, root / 'backups')
            self.assertEqual((current / 'value').read_bytes(), b'new')
            self.assertEqual((backup / 'value').read_bytes(), b'old')

    def test_busy_output_directory_uses_verified_backup_and_atomic_file_replacements(self):
        _, _, release = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current, staged = root / 'realease', root / 'pending'
            for directory in (current, staged):
                (directory / 'data').mkdir(parents=True)
                (directory / 'data/unchanged.a').write_bytes(b'unchanged archive')
            (current / 'data/sys.a').write_bytes(b'old UI')
            (staged / 'data/sys.a').write_bytes(b'Chinese UI')
            real_replace = release.os.replace

            def busy_directory(src, dst):
                if Path(src) == current:
                    raise PermissionError('Windows directory is open')
                return real_replace(src, dst)

            with patch.object(release.os, 'replace', busy_directory):
                backup = release.commit_directory(staged, current, root / 'backups')
            self.assertEqual((current / 'data/sys.a').read_bytes(), b'Chinese UI')
            self.assertEqual((backup / 'data/sys.a').read_bytes(), b'old UI')
            self.assertEqual((backup / 'data/unchanged.a').read_bytes(), b'unchanged archive')
            self.assertEqual((staged / 'data/sys.a').read_bytes(), b'Chinese UI')

    def test_failed_busy_directory_file_update_rolls_back_all_replaced_files(self):
        _, _, release = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current, staged = root / 'realease', root / 'pending'
            current.mkdir(); staged.mkdir()
            for name in ('a', 'b'):
                (current / name).write_bytes(b'old-' + name.encode())
                (staged / name).write_bytes(b'new-' + name.encode())
            real_replace = release.os.replace
            failed = False

            def busy_and_fail_once(src, dst):
                nonlocal failed
                if Path(src) == current:
                    raise PermissionError('Windows directory is open')
                if Path(dst) == current / 'b' and not failed:
                    failed = True
                    raise OSError('simulated file update failure')
                return real_replace(src, dst)

            with patch.object(release.os, 'replace', busy_and_fail_once):
                with self.assertRaisesRegex(OSError, 'file update failure'):
                    release.commit_directory(staged, current, root / 'backups')
            self.assertEqual((current / 'a').read_bytes(), b'old-a')
            self.assertEqual((current / 'b').read_bytes(), b'old-b')

    def test_busy_directory_fallback_refuses_to_discard_unlisted_user_files(self):
        _, _, release = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current, staged = root / 'realease', root / 'pending'
            current.mkdir(); staged.mkdir()
            (current / 'save.json').write_bytes(b'user save')
            (staged / 'sys.a').write_bytes(b'new UI')
            with patch.object(release.os, 'replace', side_effect=PermissionError('busy')):
                with self.assertRaisesRegex((OSError, ValueError), 'busy|file set'):
                    release.commit_directory(staged, current, root / 'backups')
            self.assertEqual((current / 'save.json').read_bytes(), b'user save')

    def test_cancelled_busy_directory_update_restores_previous_files(self):
        _, _, release = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current, staged = root / 'realease', root / 'pending'
            current.mkdir(); staged.mkdir()
            for name in ('a', 'b'):
                (current / name).write_bytes(b'old-' + name.encode())
                (staged / name).write_bytes(b'new-' + name.encode())
            real_replace = release.os.replace
            cancelled = False

            def cancel_second_file(src, dst):
                nonlocal cancelled
                if Path(src) == current:
                    raise PermissionError('Windows directory is open')
                if Path(dst) == current / 'b' and not cancelled:
                    cancelled = True
                    raise KeyboardInterrupt('cancelled by user')
                return real_replace(src, dst)

            with patch.object(release.os, 'replace', cancel_second_file):
                with self.assertRaises(KeyboardInterrupt):
                    release.commit_directory(staged, current, root / 'backups')
            for name in ('a', 'b'):
                self.assertEqual((current / name).read_bytes(), b'old-' + name.encode())

    def test_switching_sdk_does_not_reuse_cached_compiler_directory(self):
        from vita_asset_pipeline import build
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            work = project / '.work'
            directories = []

            def fake_cmake(command, log):
                # Replace only the external CMake/compiler boundary.
                if '-B' in command:
                    destination = Path(command[command.index('-B') + 1])
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / 'tenshi-vita.vpk').write_bytes(b'SDK fixture output')
                    directories.append(destination)

            base = {'prefix': [], 'distro': None, 'compiler': 'fixture gcc', 'sdkVersion': 'fixture', 'path': '/usr/bin'}
            with patch.object(build, 'run_logged', fake_cmake):
                build.build_vpk(project, work, environment={**base, 'sdk': '/sdk-a'})
                build.build_vpk(project, work, environment={**base, 'sdk': '/sdk-b'})
            self.assertNotEqual(directories[0], directories[1], 'SDK B would reuse SDK A compiler cache')

    def test_same_work_directory_rejects_concurrent_writer(self):
        _, common, _ = self.modules()
        with tempfile.TemporaryDirectory() as temporary:
            with common.work_lock(Path(temporary)):
                with self.assertRaisesRegex(RuntimeError, 'Another build'):
                    with common.work_lock(Path(temporary)):
                        self.fail('A second writer acquired the same work directory')
            self.assertFalse((Path(temporary) / 'pipeline.lock').exists())


if __name__ == '__main__':
    unittest.main()
