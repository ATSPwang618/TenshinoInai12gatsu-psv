"""Validate the actual program VPK; never extract commercial data into it."""
from pathlib import Path
import struct
import zipfile
import xml.etree.ElementTree as ET
import zlib

from .common import checked_path, file_record, read_json


def validate_shell(entries):
    images = {'sce_sys/icon0.png': (128, 128), 'sce_sys/pic0.png': (960, 544),
              'sce_sys/livearea/contents/background.png': (840, 500),
              'sce_sys/livearea/contents/startup.png': (280, 158)}
    images.update({name: (960, 544) for name in entries if name.startswith('sce_sys/manual/') and name.endswith('.png')})
    for name, size in images.items():
        data = entries[name]
        if data[:8] != b'\x89PNG\r\n\x1a\n' or len(data) < 33:
            raise ValueError('Invalid PNG: ' + name)
        if data[16:26] != struct.pack('>IIBB', *size, 8, 3):
            raise ValueError(f'{name} must be an 8-bit indexed PNG with size {size}')
        position, chunks = 8, []
        while position + 12 <= len(data):
            length, tag = struct.unpack_from('>I4s', data, position)
            end = position + 12 + length
            if end > len(data):
                raise ValueError('Truncated PNG: ' + name)
            body = data[position + 8:position + 8 + length]
            if struct.unpack_from('>I', data, position + 8 + length)[0] != zlib.crc32(tag + body):
                raise ValueError('PNG CRC mismatch: ' + name)
            chunks.append(tag)
            position = end
        if position != len(data) or not chunks or chunks[0] != b'IHDR' or chunks[-1] != b'IEND' or not {b'PLTE', b'IDAT'} <= set(chunks):
            raise ValueError('Invalid PNG chunks: ' + name)
        if name == 'sce_sys/icon0.png' and b'tRNS' in chunks:
            raise ValueError('Packaged icon must not contain transparency: ' + name)
    template = 'sce_sys/livearea/contents/template.xml'
    try:
        tree = ET.fromstring(entries[template])
    except ET.ParseError as error:
        raise ValueError('Invalid LiveArea XML: ' + template) from error
    for node in tree.iter():
        if node.tag in ('image', 'startup-image') and node.text and node.text.strip():
            name = 'sce_sys/livearea/contents/' + node.text.strip()
            checked_path(Path('.'), name)
            if name not in entries:
                raise ValueError(f'{template} references missing image: {name}')


def sfo_strings(data):
    def invalid():
        raise ValueError('Invalid param.sfo (SFO header or entry bounds)')
    if len(data) < 20:
        invalid()
    magic, version, keys, values, count = struct.unpack_from('<4s4I', data)
    if magic != b'\x00PSF' or version != 0x101 or not 20 + count * 16 <= keys <= values <= len(data):
        invalid()
    result = {}
    seen = set()
    for i in range(count):
        key_offset, kind, length, capacity, value_offset = struct.unpack_from('<HHIII', data, 20 + i * 16)
        start = keys + key_offset
        if not keys <= start < values:
            invalid()
        end = data.find(b'\x00', start, values)
        if end < 0 or length > capacity or values + value_offset + capacity > len(data):
            invalid()
        try:
            key = data[start:end].decode('utf-8')
            if key in seen:
                invalid()
            seen.add(key)
            if kind == 0x204:
                value = data[values + value_offset:values + value_offset + length]
                if not value or value[-1] != 0 or b'\x00' in value[:-1]:
                    invalid()
                result[key] = value[:-1].decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('Invalid UTF-8 in SFO') from error
    return result


def validate_vpk(project, path, opening_metadata=None):
    # Reuse the same icon/OFL transformation as both actual build paths.
    import importlib.util
    project, path = Path(project), Path(path)
    spec = importlib.util.spec_from_file_location('tenshi_vpk_resources', project / 'tools/vpk_resources.py')
    resources = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resources)
    font = 'assets/SourceHanSansCN-Regular.otf'
    font_meta = read_json(project / 'assets/source-han-sans.json')
    if file_record(project / font)['sha256'] != font_meta['fontSha256']:
        raise ValueError('Bundled font differs from pinned official release')
    expected = {name: (project / name).read_bytes() for name in
                (font, 'assets/source-han-sans.json', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'FONT_LICENSE.md')}
    expected['assets/opening.json'] = Path(opening_metadata or project / 'assets/opening.json').read_bytes()
    for folder in ('sce_sys', 'licenses'):
        for item in sorted((project / folder).rglob('*')):
            if item.is_file() and not (folder == 'sce_sys' and item.name == 'param.sfo'):
                name = item.relative_to(project).as_posix()
                expected[name] = resources.shell_bytes(item) if folder == 'sce_sys' else item.read_bytes()
    expected['licenses/SourceHanSans-OFL.txt'] = resources.font_license(project)
    for required in ('sce_sys/icon0.png', 'sce_sys/pic0.png', 'sce_sys/livearea/contents/template.xml',
                     'sce_sys/livearea/contents/background.png', 'sce_sys/livearea/contents/startup.png',
                     'sce_sys/manual/001.png'):
        if required not in expected:
            raise ValueError('Missing project shell resource: ' + required)
    validate_shell(expected)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate VPK entries')
        for name in names:
            checked_path(project / '.work/vpk-path-check', name.rstrip('/'))
            lower = name.lower()
            if name != font and (lower.endswith(('.ttf', '.otf', '.ttc', '.ogg', '.wav', '.mpg', '.mp4', '.idx', '.a', '.v'))
                                 or lower in ('manifest.json', 'prologue.json')):
                raise ValueError('Player asset in VPK: ' + name)
        if archive.testzip() is not None:
            raise ValueError('VPK ZIP CRC failed')
        unexpected = set(names) - set(expected) - {'eboot.bin', 'sce_sys/param.sfo'}
        if unexpected:
            raise ValueError('Unlisted VPK resource: ' + sorted(unexpected)[0])
        for name, data in expected.items():
            if name not in names:
                raise ValueError('Missing VPK entry: ' + name)
            if archive.read(name) != data:
                raise ValueError('Outdated VPK resource: ' + name)
        for name in ('eboot.bin', 'sce_sys/param.sfo'):
            if name not in names:
                raise ValueError('Missing VPK entry: ' + name)
        if archive.read('eboot.bin')[:4] != b'SCE\0':
            raise ValueError('Not a Vita SELF executable')
        sfo = sfo_strings(archive.read('sce_sys/param.sfo'))
        for key, value in {'TITLE': 'December When There Is No Angel', 'TITLE_ID': 'TNSH00001', 'APP_VER': '00.27'}.items():
            if sfo.get(key) != value:
                raise ValueError('Wrong VPK SFO ' + key + ': ' + repr(sfo.get(key)))
    return {**file_record(path, 'tenshi-vita.vpk'), 'entries': len(names), 'zipCrc': 'passed',
            'sourceResourcesMatch': True, 'gameArchivesBundled': False, 'openingBundled': False,
            'title': sfo['TITLE'], 'titleId': sfo['TITLE_ID'], 'version': sfo['APP_VER']}
