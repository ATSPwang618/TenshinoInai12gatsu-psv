"""Run launcher interfaces, including failure paths before any SDK is invoked."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PipelineCliTest(unittest.TestCase):
    def run_cli(self, path, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / path), *args],
                              capture_output=True, text=True, encoding='utf-8')

    def test_prepare_help_exposes_resource_and_build_controls(self):
        result = self.run_cli('prepare-tenshi-vita.py', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ('--build', '--check', '--output', '--work-dir', '--ffmpeg', '--wsl'):
            self.assertIn(flag, result.stdout)

    def test_build_help_exposes_existing_wsl_sdk_selection(self):
        result = self.run_cli('tools/build-vita.py', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ('--source', '--wsl', '--sdk', '--check'):
            self.assertIn(flag, result.stdout)

    def test_unsafe_source_or_output_fails_without_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'missing-original'
            output = Path(temporary) / 'output'
            result = self.run_cli('prepare-tenshi-vita.py', str(source), '--output', str(output))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
