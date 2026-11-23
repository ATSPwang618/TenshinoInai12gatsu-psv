"""Stage install-compatible shell resources without changing source artwork."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import zlib


def icon_bytes(path):
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n' or data[16:26] != struct.pack('>IIBB', 128, 128, 8, 3):
        raise RuntimeError('icon0.png must be a 128x128 8-bit indexed PNG')
    chunks = []
    pos = 8
    while pos + 12 <= len(data):
        size, kind = struct.unpack_from('>I4s', data, pos)
        end = pos + 12 + size
        if end > len(data):
            raise RuntimeError('Truncated icon PNG')
        chunks.append((kind, data[pos + 8:pos + 8 + size]))
        pos = end
    if pos != len(data) or not chunks or chunks[-1][0] != b'IEND':
        raise RuntimeError('Invalid icon PNG chunks')
    transparency = dict(chunks).get(b'tRNS')
    if transparency is None:
        return data
    # Flatten the palette on pale sage. Keep all indexed pixels and opaque
    # colours intact, and avoid encoder/Pillow-version-dependent quantization.
    result = bytearray(data[:8])
    for kind, body in chunks:
        if kind == b'tRNS':
            continue
        if kind == b'PLTE':
            palette = bytearray(body)
            for i in range(len(body) // 3):
                alpha = transparency[i] if i < len(transparency) else 255
                for channel, background in enumerate((238, 243, 223)):
                    palette[i * 3 + channel] = (body[i * 3 + channel] * alpha + background * (255 - alpha) + 127) // 255
            body = bytes(palette)
        result.extend(struct.pack('>I', len(body)) + kind + body
                      + struct.pack('>I', zlib.crc32(kind + body)))
    return bytes(result)


def font_license(root):
    data = (root / 'licenses/SourceHanSans-OFL.txt').read_bytes().replace(b'\r\n', b'\n')
    meta = json.loads((root / 'assets/source-han-sans.json').read_text(encoding='utf-8'))
    if hashlib.sha256(data).hexdigest() != meta['licenseSha256']:
        raise RuntimeError('Font license differs from pinned official release')
    return data


def shell_bytes(path):
    return icon_bytes(path) if path.name == 'icon0.png' else path.read_bytes()


def prepare(root, output):
    root, output = root.resolve(), output.resolve()
    for protected in (root / 'sce_sys', root / 'licenses', root / 'assets'):
        if output == root or output == protected or output in protected.parents or protected in output.parents:
            raise RuntimeError('Build output must not overlap source resources')
    files = {}
    for folder in ('sce_sys', 'licenses'):
        for source in sorted((root / folder).rglob('*')):
            if not source.is_file() or (folder == 'sce_sys' and source.name == 'param.sfo'):
                continue
            # Existing Markdown notices are packaged directly from their originals.
            if source.suffix.lower() == '.md':
                continue
            entry = source.relative_to(root).as_posix()
            data = shell_bytes(source) if folder == 'sce_sys' else source.read_bytes()
            if entry == 'licenses/SourceHanSans-OFL.txt':
                data = font_license(root)
            target = output / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != data:
                target.write_bytes(data)
            files[entry] = {'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                            'packageSha256': hashlib.sha256(data).hexdigest()}
    (output / 'resources.json').write_text(json.dumps(files, indent=2) + '\n', encoding='utf-8')
    return files


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps({'stagedFiles': len(prepare(args.root, args.output))}))
