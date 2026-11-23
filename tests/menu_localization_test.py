"""Synthetic archives only: localization must never need commercial test fixtures."""
import importlib
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class MenuLocalizationTest(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('vita_asset_pipeline.menu'),
                             'The reproducible menu localization step is missing')
        return importlib.import_module('vita_asset_pipeline.menu')

    def test_lzss_known_literals_zero_window_and_overlapping_copy(self):
        m = self.module()
        self.assertEqual(m.unpack(struct.pack('<I', 3) + b'\x07ABC'), b'ABC')
        self.assertEqual(m.unpack(struct.pack('<I', 3) + b'\x00\x00\x00'), bytes(3))
        self.assertEqual(m.unpack(struct.pack('<I', 6) + b'\x01A\xee\xf2'), b'AAAAAA')
        for source in (b'AB' * 4098, bytes(range(256)) * 32, bytes(100), b'abc'):
            self.assertEqual(m.unpack(m.pack(source)), source)
        for malformed in (b'', struct.pack('<I', 0), struct.pack('<I', 200_000_000),
                          struct.pack('<I', 1) + b'\x01'):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                m.unpack(malformed)

    def test_px_replacement_preserves_other_frames_geometry_and_transparency(self):
        from PIL import Image
        m = self.module()
        # Odd alpha for low-red pixels is representable exactly by the native PX codec.
        source = Image.new('RGBA', (4, 2), (12, 34, 56, 255))
        source.putpixel((0, 0), (0, 0, 0, 0))
        source.putpixel((1, 0), (12, 34, 56, 127))
        first = m.encode_image(source, (-3, 7))
        second = m.encode_image(Image.new('RGBA', (2, 3), (10, 20, 30, 255)), (4, -5))
        atlas = m.make_atlas([first, second])
        changed = m.replace_frames(atlas, {0: m.encode_image(source, (-3, 7))})
        self.assertEqual(m.split_atlas(changed)[1], second)
        decoded, origin = m.decode_image(m.split_atlas(changed)[0])
        self.assertEqual(origin, (-3, 7))
        self.assertEqual(decoded.tobytes(), source.tobytes())
        with self.assertRaises(ValueError):
            m.replace_frames(atlas, {2: first})
        with self.assertRaises(ValueError):
            m.split_atlas(atlas[:20])

    def test_direct_px_alpha_uses_red_high_bit_like_native_decoder(self):
        m = self.module()
        header = struct.pack('<IIiiIIII', 2, 1, 0, 0, 0x200001, 0, 0, 0)
        image, _ = m.decode_image(header + bytes([128, 0, 0, 64, 0, 0, 128, 64]))
        self.assertEqual(list(image.getdata()), [(0, 0, 128, 127), (128, 0, 0, 128)])

    def test_archive_repack_preserves_duplicate_rows_kinds_and_unmodified_payloads(self):
        m = self.module()
        rows = [(b'Title.PX', 0, b'legacy'), (b'title.px', 128, b'preferred'),
                (b'music.w', 7, b'untouched')]
        archive = m.make_archive(rows)
        replaced = m.patch_archive(archive, {'title.px': b'localized'})
        self.assertEqual(m.read_archive(replaced),
                         [(b'Title.PX', 0, b'legacy'), (b'title.px', 128, b'localized'),
                          (b'music.w', 7, b'untouched')])
        self.assertEqual(m.read_archive(archive), rows)
        with self.assertRaises(ValueError):
            m.patch_archive(archive, {'missing.px': b'bad'})
        with self.assertRaises(ValueError):
            m.read_archive(archive[:10])

    def test_text_edit_keeps_border_and_clears_old_glyphs(self):
        from PIL import Image
        m = self.module()
        source = Image.new('RGBA', (160, 42), (50, 75, 80, 255))
        source.putpixel((45, 15), (255, 0, 0, 255))
        rule = {'box': [9, 5, 149, 30], 'text': '开始游戏', 'size': 22,
                'erase': 'row', 'sampleX': 150}
        result = m.render(source, rule, ROOT / 'assets/SourceHanSansCN-Regular.otf')
        self.assertEqual(result.getpixel((0, 0)), source.getpixel((0, 0)))
        self.assertNotIn((255, 0, 0, 255), list(result.getdata()))
        self.assertNotEqual(result.tobytes(), source.tobytes())
        self.assertEqual(result.size, source.size)
        with self.assertRaises(ValueError):
            m.render(source, {**rule, 'box': [-1, 0, 5, 5]}, ROOT / 'assets/SourceHanSansCN-Regular.otf')

    def test_generated_archive_is_readable_by_actual_native_runtime_decoder(self):
        import shutil
        import subprocess
        from PIL import Image
        compiler = shutil.which('g++') or shutil.which('c++')
        if not compiler:
            self.skipTest('Host C++ compiler not available; Linux CI runs the native decoder test')
        m = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / 'menu-codec-test'
            subprocess.run([compiler, '-std=c++17', '-O1', '-I', str(ROOT / 'src'),
                            str(ROOT / 'tests/menu_codec_test.cpp'), '-o', str(executable)], check=True)
            pixels = Image.new('RGBA', (3, 2))
            pixels.putdata([(0, 0, 0, 0), (10, 20, 30, 127), (10, 20, 30, 255),
                            (200, 150, 100, 254), (64, 120, 220, 1), (0, 0, 0, 255)])
            atlas = m.make_atlas([m.encode_image(pixels, (-4, 5))])
            archive = root / 'fixture.a'
            archive.write_bytes(m.make_archive([(b'test.px', 0, m.pack(atlas))]))
            decoded = root / 'native.rgba'
            result = subprocess.run([str(executable), str(archive), str(decoded)],
                                    check=True, text=True, capture_output=True)
            self.assertEqual(result.stdout.strip(), '3 2 -4 5')
            self.assertEqual(decoded.read_bytes(), bytes([
                0, 0, 0, 0, 10, 20, 30, 127, 10, 20, 30, 255,
                200, 150, 100, 254, 64, 120, 220, 1, 0, 0, 0, 255]))

    def test_recipe_erases_baked_panel_text_below_translucent_controls(self):
        from PIL import Image
        from vita_asset_pipeline.common import read_json
        m = self.module()
        recipe = read_json(ROOT / 'assets/menu-zh-cn.json')
        source = Image.new('RGBA', (560, 360), (26, 48, 96, 175))
        source.putpixel((250, 40), (255, 0, 0, 255))
        for rule in recipe['atlases']['system.px']:
            if 0 in rule['frames']:
                source = m.render(source, rule, ROOT / recipe['font'])
        self.assertEqual(source.getpixel((250, 40)), (26, 48, 96, 175),
                         'Original Japanese on panel must not show through translated buttons')

    def test_narrow_button_erasure_samples_interior_not_white_border(self):
        from PIL import Image
        from vita_asset_pipeline.common import read_json
        m = self.module()
        recipe = read_json(ROOT / 'assets/menu-zh-cn.json')
        source = Image.new('RGBA', (129, 52), (53, 77, 90, 199))
        source.paste((255, 255, 255, 255), (121, 0, 122, 52))
        rule = next(r for r in recipe['atlases']['system.px'] if 50 in r['frames'])
        image = m.render(source, rule, ROOT / recipe['font'])
        self.assertEqual(image.getpixel((9, 6)), (53, 77, 90, 199))

    def test_localization_recipe_and_font_change_invalidate_asset_cache(self):
        # The transform is real; only the slow movie encoder is substituted.
        from asset_pipeline_test import AssetPipelineTest
        from vita_asset_pipeline import package
        m = self.module()
        from PIL import Image
        import json
        import shutil
        from vita_asset_pipeline.common import file_record
        helpers = AssetPipelineTest()
        with tempfile.TemporaryDirectory() as temporary:
            project, source = helpers.fixture(temporary)
            pixels = m.encode_image(Image.new('RGBA', (160, 42), (10, 20, 30, 255)), (0, 0))
            (source / 'sys.a').write_bytes(m.make_archive([(b'title.px', 0, m.pack(m.make_atlas([pixels])))]))
            manifest = json.loads((project / 'assets/game-data.json').read_text())
            manifest['files'] = [file_record(source / row['path']) for row in manifest['files']]
            (project / 'assets/game-data.json').write_text(json.dumps(manifest))
            shutil.copyfile(ROOT / 'assets/SourceHanSansCN-Regular.otf', project / 'assets/font.otf')
            recipe = {'schema': 'tenshi-menu-zh-cn-v1', 'font': 'assets/font.otf', 'atlases': {
                'title.px': [{'frames': [0], 'box': [5, 5, 155, 35], 'size': 22,
                              'text': '开始游戏', 'erase': 'row', 'sampleX': 156}]}}
            recipe_path = project / 'assets/menu-zh-cn.json'
            recipe_path.write_text(json.dumps(recipe), encoding='utf-8')
            with patch.object(package, 'convert_opening', helpers.converter):
                first = helpers.prepare(package, project, source)
                self.assertNotEqual((first['data'] / 'sys.a').read_bytes(), (source / 'sys.a').read_bytes())
                second = helpers.prepare(package, project, source)
                self.assertTrue(second['cacheHit'])
                recipe['atlases']['title.px'][0]['text'] = '继续游戏'
                recipe_path.write_text(json.dumps(recipe), encoding='utf-8')
                third = helpers.prepare(package, project, source)
                self.assertNotEqual(third['key'], first['key'])
                self.assertFalse(third['cacheHit'])
                with (project / 'assets/font.otf').open('ab') as stream:
                    stream.write(b'font identity change')
                fourth = helpers.prepare(package, project, source)
                self.assertNotEqual(fourth['key'], third['key'])
                self.assertEqual(m.read_archive((source / 'sys.a').read_bytes())[0][0], b'title.px')


if __name__ == '__main__':
    unittest.main()
