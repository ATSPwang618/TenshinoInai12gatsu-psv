"""Compile the real App path method alone for Vita and host, without SDL/UI."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OpeningPathTest(unittest.TestCase):
    def test_vita_reads_external_mp4_and_host_keeps_original_video(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('Run inside WSL with c++ available')
        source = (ROOT / 'src/main.cpp').read_text(encoding='utf-8')
        start = source.index('    std::string openingPath() const {')
        end = source.index('\n    }', start) + len('\n    }')
        method = source[start:end]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'test.cpp').write_text('#include <string>\n#include <iostream>\n'
                'struct App { std::string root;\n' + method + '\n};\n'
                'int main() { std::cout << App{"ux0:/data/tenshi"}.openingPath(); }\n')
            for flags, expected in [(['-D__vita__'], 'ux0:/data/tenshi/opening.mp4'),
                                    ([], 'ux0:/data/tenshi/openning.v')]:
                with self.subTest(flags=flags):
                    subprocess.run([compiler, str(root / 'test.cpp'), '-o', str(root / 'test'), *flags], check=True)
                    actual = subprocess.check_output([str(root / 'test')], text=True)
                    self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
