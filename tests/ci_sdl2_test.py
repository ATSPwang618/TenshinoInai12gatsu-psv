"""Exercise the CI SDL2 backend gate with real compiled static libraries."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CiSdl2Test(unittest.TestCase):
    def setUp(self):
        self.cc = shutil.which('cc') or shutil.which('gcc')
        self.ar, self.nm = shutil.which('ar'), shutil.which('nm')
        if not all((self.cc, self.ar, self.nm)):
            self.skipTest('Host C compiler and binutils required')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.sdk = Path(self.temporary.name)
        self.library = self.sdk / 'arm-vita-eabi/lib/libSDL2.a'
        self.library.parent.mkdir(parents=True)

    def archive(self, source):
        path = self.sdk / 'backend.c'
        path.write_text(source, encoding='utf-8')
        obj = self.sdk / 'backend.o'
        subprocess.run([self.cc, '-c', str(path), '-o', str(obj)], check=True)
        subprocess.run([self.ar, 'rcs', str(self.library), str(obj)], check=True)

    def check(self):
        return subprocess.run([sys.executable, str(ROOT / 'tools/check-vita-sdl2.py'),
                               '--sdk', str(self.sdk), '--nm', self.nm],
                              capture_output=True, text=True, encoding='utf-8')

    def test_native_gxm_archive_is_accepted(self):
        self.archive('int VITA_GXM_RenderDriver = 1; int SDL_Init(void) { return 0; }')
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GXM', result.stdout)

    def test_mixed_gxm_and_vitagl_archive_is_rejected_before_link(self):
        self.archive('int VITA_GXM_RenderDriver = 1; extern void vglInitExtended(void); '
                     'void SDL_Init(void) { vglInitExtended(); }')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('vglInitExtended', result.stderr)

    def test_pvr_or_other_gl_dependencies_are_rejected(self):
        self.archive('int VITA_GXM_RenderDriver = 1; extern void eglSwapInterval(void); '
                     'void SDL_Init(void) { eglSwapInterval(); }')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('eglSwapInterval', result.stderr)

    def test_standard_gl_dependencies_are_rejected(self):
        self.archive('int VITA_GXM_RenderDriver = 1; extern void glFinish(void); '
                     'void SDL_Init(void) { glFinish(); }')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('glFinish', result.stderr)

    def test_archive_without_gxm_renderer_is_rejected(self):
        self.archive('int SDL_Init(void) { return 0; }')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing VITA_GXM_RenderDriver', result.stderr)


if __name__ == '__main__':
    unittest.main()
