"""Execute both packaging configurations with only SDK boundaries replaced."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]


def copy_resource_inputs(root):
    (root / 'tools').mkdir(exist_ok=True)
    helper = ROOT / 'tools/vpk_resources.py'
    if helper.exists():
        shutil.copy2(helper, root / 'tools/vpk_resources.py')
    shutil.copytree(ROOT / 'licenses', root / 'licenses', dirs_exist_ok=True)
    (root / 'assets').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'assets/source-han-sans.json', root / 'assets/source-han-sans.json')


class BuildMetadataTest(unittest.TestCase):
    def test_cmake_passes_title_and_every_shell_file_to_sdk(self):
        cmake = shutil.which('cmake')
        if not cmake:
            self.skipTest('CMake is required')
        with tempfile.TemporaryDirectory(prefix='tenshi-cmake-test-') as temporary:
            root = Path(temporary)
            shutil.copy2(ROOT / 'CMakeLists.txt', root / 'CMakeLists.txt')
            shutil.copytree(ROOT / 'sce_sys', root / 'sce_sys')
            copy_resource_inputs(root)
            (root / 'src').mkdir()
            (root / 'src/main.cpp').write_text('int main() { return 0; }\n')
            (root / 'sce_sys/manual/002.png').write_bytes(b'additional-page-fixture')
            (root / 'sce_sys/param.sfo').write_bytes(b'stale-source-SFO')
            share = root / 'sdk/share'
            share.mkdir(parents=True)
            compiler = Path(cmake).as_posix()
            toolchain = share / 'vita.toolchain.cmake'
            toolchain.write_text('set(CMAKE_SYSTEM_NAME Generic)\n' + ''.join(
                f'set(CMAKE_{language}_COMPILER "{compiler}")\n'
                f'set(CMAKE_{language}_COMPILER_FORCED TRUE)\n'
                f'set(CMAKE_{language}_COMPILER_ID_RUN TRUE)\n'
                f'set(CMAKE_{language}_COMPILER_ID GNU)\n'
                f'set(CMAKE_{language}_COMPILER_VERSION 12.0)\n'
                for language in ('C', 'CXX')), encoding='utf-8')
            # SDK macro boundary: configure the real project, but do not compile.
            (share / 'vita.cmake').write_text(
                'function(vita_create_self)\nendfunction()\n'
                'function(vita_create_vpk)\n'
                'file(WRITE "${CMAKE_BINARY_DIR}/package-args.txt" "${ARGV}")\n'
                'endfunction()\n', encoding='utf-8')
            result = subprocess.run([cmake, '-S', str(root), '-B', str(root / 'build'),
                                     '-G', 'Unix Makefiles', '-DCMAKE_MAKE_PROGRAM=' + compiler,
                                     '-DCMAKE_TOOLCHAIN_FILE=' + str(toolchain),
                                     '-DPython3_EXECUTABLE=' + sys.executable,
                                     '-DVITASDK=' + str(root / 'sdk')],
                                    cwd=root, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            args = (root / 'build/package-args.txt').read_text().split(';')
            self.assertEqual(args[:7], ['tenshi-vita.vpk', 'TNSH00001', 'eboot.bin',
                                       'VERSION', '00.27', 'NAME', 'December When There Is No Angel'])
            files = {args[i + 2]: args[i + 1] for i, value in enumerate(args) if value == 'FILE'}
            for entry in ('sce_sys/icon0.png', 'sce_sys/pic0.png',
                          'sce_sys/livearea/contents/template.xml',
                          'sce_sys/livearea/contents/background.png',
                          'sce_sys/livearea/contents/startup.png',
                          'sce_sys/manual/001.png', 'sce_sys/manual/002.png'):
                self.assertEqual(files.get(entry), (root / 'build/vpk-resources' / entry).as_posix())
            self.assertNotIn('sce_sys/param.sfo', files)
            self.assertNotIn('assets/opening.mp4', files)
            self.assertNotIn('assets/opening.idx', files)
            self.assertEqual(files['licenses/SourceHanSans-OFL.txt'],
                             (root / 'build/vpk-resources/licenses/SourceHanSans-OFL.txt').as_posix())

    def test_powershell_passes_title_and_every_shell_file_to_sdk(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 is required')
        with tempfile.TemporaryDirectory(prefix='tenshi-build-test-') as temporary:
            root = Path(temporary)
            (root / 'tools').mkdir()
            (root / 'licenses').mkdir()
            shutil.copytree(ROOT / 'sce_sys', root / 'sce_sys')
            copy_resource_inputs(root)
            # An additional page must be collected; a stale source SFO must not.
            (root / 'sce_sys/manual/002.png').write_bytes(b'additional-page-fixture')
            (root / 'sce_sys/param.sfo').write_bytes(b'stale-source-sfo')
            script = (ROOT / 'tools/build-vita-native.ps1').read_text(encoding='utf-8-sig')
            start = script.index('function Run-Tool(')
            end = script.index('\n}', start) + 2
            replacement = '''$script:capturedTools = @()
function Run-Tool([string]$Name,[string[]]$ToolArgs) {
    $script:capturedTools += [PSCustomObject]@{Name=$Name; Arguments=$ToolArgs}
}'''
            script = script[:start] + replacement + script[end:]
            script += '\n$script:capturedTools | ConvertTo-Json -Depth 6 -Compress\n'
            script_path = root / 'tools/build-vita-native.ps1'
            script_path.write_text(script, encoding='utf-8')
            result = subprocess.run([pwsh, '-NoProfile', '-File', str(script_path), '-Python', sys.executable],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = {call['Name']: call['Arguments'] for call in json.loads(result.stdout.splitlines()[-1])}
            sfo_args = calls['vita-mksfoex']
            self.assertEqual(sfo_args[-2], 'December When There Is No Angel')
            self.assertIn('TITLE_ID=TNSH00001', sfo_args)
            self.assertIn('APP_VER=00.27', sfo_args)
            args = calls['vita-pack-vpk']
            files = dict(args[i + 1].split('=', 1)[::-1]
                         for i, value in enumerate(args[:-1]) if value == '-a')
            for entry in ('sce_sys/icon0.png', 'sce_sys/pic0.png',
                          'sce_sys/livearea/contents/template.xml',
                          'sce_sys/livearea/contents/background.png',
                          'sce_sys/livearea/contents/startup.png',
                          'sce_sys/manual/001.png', 'sce_sys/manual/002.png'):
                with self.subTest(entry=entry):
                    self.assertIn(entry, files)
                    self.assertEqual(Path(files[entry]), root / '.work/build-vita-native/vpk-resources' / entry)
                    if entry != 'sce_sys/icon0.png':
                        self.assertEqual(Path(files[entry]).read_bytes(), (root / entry).read_bytes())
            self.assertNotIn('sce_sys/param.sfo', files)
            self.assertNotIn('assets/opening.mp4', files)
            self.assertNotIn('assets/opening.idx', files)
            self.assertTrue(args[-1].replace('\\', '/').endswith('/.work/build-vita-native/tenshi-vita.vpk'))


if __name__ == '__main__':
    unittest.main()
