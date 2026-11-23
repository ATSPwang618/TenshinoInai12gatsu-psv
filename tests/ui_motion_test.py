"""Run actual UI animation/color logic with a host C++ compiler, without game data."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UiMotionTest(unittest.TestCase):
    def test_animation_boundaries_grayscale_and_feedback(self):
        compiler = shutil.which('c++') or shutil.which('g++')
        if not compiler:
            self.skipTest('Host C++ compiler required')
        self.assertTrue((ROOT / 'src/ui_motion.hpp').is_file(),
                        'The runtime needs a tested UI transition and grayscale implementation')
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'ui-motion-test'
            build = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra',
                                    '-I', str(ROOT / 'src'), str(ROOT / 'tests/ui_motion_test.cpp'),
                                    '-o', str(executable)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('timed feedback passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
