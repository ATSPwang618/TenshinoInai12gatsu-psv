"""Local-only Chinese UI transform. No commercial images are stored in the repo.

PX decoding follows src/media.hpp (GARbro MIT attribution in licenses/GARbro-MIT.txt).
Only selected frames are re-encoded; other frame and archive payloads stay byte-identical.
"""
from collections import defaultdict, deque
from pathlib import Path
import struct

from .common import checked_path, file_record, read_json


LIMIT = 128 * 1024 * 1024


def word(data, at=0):
    if at < 0 or at + 4 > len(data):
        raise ValueError('Truncated PX/LZSS data')
    return struct.unpack_from('<I', data, at)[0]


def unpack(data):
    size = word(data)
    if not 0 < size <= LIMIT:
        raise ValueError('Invalid LZSS output size')
    result = bytearray()
    p = 4
    while len(result) < size:
        if p >= len(data):
            raise ValueError('Truncated LZSS flags')
        flags = data[p]
        p += 1
        for bit in range(8):
            if len(result) >= size:
                break
            if flags & (1 << bit):
                if p >= len(data):
                    raise ValueError('Truncated LZSS literal')
                result.append(data[p])
                p += 1
            else:
                if p + 2 > len(data):
                    raise ValueError('Truncated LZSS reference')
                lo, hi = data[p:p + 2]
                p += 2
                distance = (0xfee + len(result) - (lo | ((hi & 0xf0) << 4))) & 4095
                distance = distance or 4096
                for _ in range(min((hi & 15) + 3, size - len(result))):
                    result.append(result[-distance] if len(result) >= distance else 0)
    return bytes(result)


def pack(data):
    if not 0 < len(data) <= LIMIT:
        raise ValueError('Invalid LZSS input size')
    # Bounded hash chains; offsets use exactly the native decoder's 0xfee ring.
    chains = defaultdict(deque)
    out = bytearray(struct.pack('<I', len(data)))
    p = 0
    while p < len(data):
        flag_at = len(out)
        out.append(0)
        for bit in range(8):
            if p >= len(data):
                break
            key = data[p:p + 3]
            candidates = chains[key]
            while candidates and candidates[0] < p - 4096:
                candidates.popleft()
            best, match = 0, 0
            for at in reversed(candidates):
                n = 0
                while n < min(18, len(data) - p) and data[at + n] == data[p + n]:
                    n += 1
                if n > best:
                    best, match = n, at
                    if best == 18:
                        break
            count = best if best >= 3 else 1
            if count == 1:
                out[flag_at] |= 1 << bit
                out.append(data[p])
            else:
                at = (0xfee + match) & 4095
                out.extend((at & 255, ((at >> 4) & 0xf0) | (count - 3)))
            for at in range(p, p + count):
                chain = chains[data[at:at + 3]]
                chain.append(at)
                if len(chain) > 64:
                    chain.popleft()
            p += count
    return bytes(out)


def read_archive(data):
    if len(data) < 4 or data[:2] != b'\x1e\xaf':
        raise ValueError('Invalid archive signature')
    count = struct.unpack_from('<H', data, 2)[0]
    base = 4 + count * 32
    if base > len(data):
        raise ValueError('Truncated archive index')
    rows = []
    for i in range(count):
        row = data[4 + i * 32:36 + i * 32]
        size, offset = struct.unpack_from('<II', row, 24)
        if base + offset + size > len(data):
            raise ValueError('Archive payload out of bounds')
        # Retain all 23 name bytes, including any padding, on repack.
        rows.append((row[:23].rstrip(b'\0'), row[23], data[base + offset:base + offset + size]))
    return rows


def make_archive(rows):
    if len(rows) > 65535:
        raise ValueError('Too many archive entries')
    table, payload = bytearray(), bytearray()
    for name, kind, content in rows:
        if not 0 < len(name) <= 23 or not 0 <= kind <= 255:
            raise ValueError('Invalid archive entry')
        table.extend(name.ljust(23, b'\0') + bytes([kind]) + struct.pack('<II', len(content), len(payload)))
        payload.extend(content)
    return struct.pack('<HH', 0xaf1e, len(rows)) + table + payload


def patch_archive(data, replacements):
    rows = read_archive(data)
    selected = {}
    for i, (name, kind, _) in enumerate(rows):
        key = name.split(b'\0', 1)[0].decode('ascii').lower()
        if key not in selected or (rows[selected[key]][1] < 128 <= kind):
            selected[key] = i
    for name, content in replacements.items():
        if name not in selected:
            raise ValueError('Missing UI archive entry: ' + name)
        i = selected[name]
        rows[i] = (*rows[i][:2], content)
    return make_archive(rows)


def split_atlas(data):
    count = word(data)
    if not 0 < count <= 1024 or word(data, 16) != 0x80 or data[20:32] != b'LeafAquaPlus':
        raise ValueError('Invalid PX atlas')
    base = 32 + count * 4
    offsets = [base] + [base + word(data, 36 + i * 4) for i in range(count - 1)] + [len(data)]
    if offsets[0] > len(data) or any(b - a < 32 for a, b in zip(offsets, offsets[1:])):
        raise ValueError('Invalid PX frame offsets')
    return [data[a:b] for a, b in zip(offsets, offsets[1:])]


def make_atlas(frames, header=None):
    if not 0 < len(frames) <= 1024:
        raise ValueError('Invalid PX frame count')
    head = bytearray(header[:36] if header is not None else bytes(36))
    struct.pack_into('<I', head, 0, len(frames))
    struct.pack_into('<I', head, 16, 0x80)
    head[20:32] = b'LeafAquaPlus'
    offset = 0
    for frame in frames[:-1]:
        offset += len(frame)
        head.extend(struct.pack('<I', offset))
    return bytes(head) + b''.join(frames)


def replace_frames(data, replacements):
    frames = split_atlas(data)
    for i, frame in replacements.items():
        if not 0 <= i < len(frames):
            raise ValueError('UI frame is out of range')
        frames[i] = frame
    return make_atlas(frames, data)


def decode_image(data):
    from PIL import Image
    fmt = word(data, 16)
    composite = fmt & 0xffff in (0x40, 0x44)
    w, h = word(data, 20 if composite else 0), word(data, 24 if composite else 4)
    if not 0 < w <= 8192 or not 0 < h <= 8192 or w * h * 4 > LIMIT:
        raise ValueError('Invalid PX dimensions')
    origin = struct.unpack_from('<ii', data, 8)
    output = bytearray(w * h * 4)

    def block(start, end, bw, bh, x, y, kind, bits, palette):
        if not 0 < bw <= 1024 or not 0 < bh <= 8192 or start > end or end > len(data):
            raise ValueError('Invalid PX block dimensions')
        p, pos, alpha = start, 0, True
        while True:
            if p + 4 > end:
                raise ValueError('Truncated PX run')
            code = struct.unpack_from('<i', data, p)[0]
            p += 4
            if code == -1:
                break
            if bits == 9:
                if code & 0x180000:
                    alpha = not alpha
                pos += (code & 0x1ff) * 1024 + (code >> 21)
                count = (code >> 9) & 0x3ff
                width = 2 if alpha else 1
            else:
                if code < 0 or code > 0xffffff:
                    continue
                pos += code // 4
                if p + 8 > end:
                    raise ValueError('Truncated PX color run')
                count = struct.unpack_from('<i', data, p + 4)[0]
                p += 8
                width = 6 if bits == 48 else 4
            if count < 0 or p + count * width > end:
                raise ValueError('Invalid PX run length')
            for _ in range(count):
                if bits == 9:
                    a = ((data[p] * 2 - 1) & 255) if alpha else 255
                    c = data[p + (1 if alpha else 0)] * 4
                    if c + 4 > len(palette):
                        raise ValueError('Invalid PX palette')
                    b, g, r = palette[c:c + 3]
                else:
                    b, g, r, a = data[p:p + 4]
                    a = (0 if bits == 48 else 255) if a == 0 else ((a * 2 + (r >> 7) + 255) & 255)
                tx, ty = x + pos % 1024, y + pos // 1024
                if 0 <= pos < bh * 1024 and pos % 1024 < bw and 0 <= tx < w and 0 <= ty < h:
                    at = (ty * w + tx) * 4
                    output[at:at + 4] = bytes((r, g, b, a))
                p += width
                pos += 1

    if composite:
        count = word(data)
        base = 32 + count * 4
        if not 0 < count <= 1024 or base > len(data):
            raise ValueError('Invalid composite PX table')
        palette = b''
        for i in range(count):
            p = base + word(data, 32 + i * 4)
            end = base + word(data, 36 + i * 4) if i + 1 < count else len(data)
            if p < base or end > len(data) or p + 32 > end:
                raise ValueError('Invalid PX block bounds')
            bw, bh, x, y, kind, bits = struct.unpack_from('<iiiiHH', data, p)
            if kind == 0 and bits == 32:
                if not 0 < bw <= 256 or p + 32 + bw * 4 > end:
                    raise ValueError('Invalid PX palette')
                palette = data[p + 32:p + 32 + bw * 4]
            elif kind == 4 and bits in (9, 32, 48):
                block(p + 32, end, bw, bh, x, y, kind, bits, palette)
            else:
                raise ValueError('Unsupported PX block')
    elif fmt in (0x200004, 0x300004):
        block(32, len(data), w, h, 0, 0, 4, 48 if fmt == 0x300004 else 32, b'')
    elif (fmt == 0x200001 and len(data) == 32 + w * h * 4) or (
            fmt == 0x80007 and len(data) == 32 + 1024 + w * h):
        for i in range(w * h):
            at = 32 + (i * 4 if fmt == 0x200001 else data[32 + 1024 + i] * 4)
            b, g, r, a = data[at:at + 4]
            a = 255 if a == 0 else ((a * 2 + (r >> 7) + 255) & 255)
            output[i * 4:i * 4 + 4] = bytes((r, g, b, a))
    else:
        raise ValueError(f'Unsupported PX format: {fmt:x}')
    return Image.frombytes('RGBA', (w, h), bytes(output)), origin


def encode_image(image, origin):
    w, h = image.size
    if not 0 < w <= 1024 or not 0 < h <= 8192 or w * h * 4 > LIMIT:
        raise ValueError('Invalid PX output dimensions')
    out = bytearray(struct.pack('<IIiiIIII', w, h, *origin, 0x300004, 0, 0, 0))
    pixels = image.convert('RGBA').tobytes()
    for y in range(h):
        out.extend(struct.pack('<iii', (1024 - w) * 4 if y else 0, 0, w))
        for p in range(y * w * 4, (y + 1) * w * 4, 4):
            r, g, b, a = pixels[p:p + 4]
            # PX alpha has 7 effective bits; nearest representable value differs by <= 1.
            a = min(128 - (r >> 7), max(1, (a + 2 - (r >> 7)) // 2)) if a else 0
            out.extend((b, g, r, a, 0, 0))
    out.extend(struct.pack('<i', -1))
    return bytes(out)


def render(image, rule, font_path):
    from PIL import Image, ImageDraw, ImageFont
    image = image.copy()
    box = tuple(rule['box'])
    x0, y0, x1, y1 = box
    if not 0 <= x0 < x1 <= image.width or not 0 <= y0 < y1 <= image.height:
        raise ValueError('UI text rectangle is out of bounds')
    # Erasure samples only known text-free columns/rows, preserving the original gradients.
    erase = rule.get('erase', 'none' if 'template' in rule else 'row')
    if erase == 'row':
        sx = rule['sampleX']
        if not 0 <= sx < image.width:
            raise ValueError('UI erasure sample is out of bounds')
        for y in range(y0, y1):
            image.paste(image.getpixel((sx, y)), (x0, y, x1, y + 1))
    elif erase == 'solid':
        image.paste(tuple(rule.get('background', [0, 0, 0, 0])), box)
    elif erase == 'none':
        pass
    else:
        raise ValueError('Unknown UI erasure mode')
    if not rule.get('text'):
        return image
    rotate = rule.get('rotate', 0)
    width, height = (y1 - y0, x1 - x0) if rotate else (x1 - x0, y1 - y0)
    scale = 3
    layer = Image.new('RGBA', (width * scale, height * scale))
    draw = ImageDraw.Draw(layer)
    size = rule.get('size', 24)
    text = rule['text']
    # BASIC avoids platform-dependent shaping defaults; font and FreeType are cache inputs.
    while size >= 8:
        font = ImageFont.truetype(str(font_path), size * scale, layout_engine=ImageFont.Layout.BASIC)
        bounds = draw.multiline_textbbox((0, 0), text, font=font, spacing=3 * scale)
        tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if tw <= width * scale - 4 and th <= height * scale - 2:
            break
        size -= 1
    else:
        raise ValueError('Chinese UI text does not fit: ' + text)
    left = 0 if rule.get('align') == 'left' else (width * scale - tw) // 2
    draw.multiline_text((left - bounds[0], (height * scale - th) // 2 - bounds[1]), text,
                        font=font, spacing=3 * scale, fill=tuple(rule.get('color', [255, 255, 255, 255])),
                        align=rule.get('align', 'center'))
    layer = layer.resize((width, height), Image.Resampling.LANCZOS)
    if rotate:
        layer = layer.rotate(rotate, expand=True)
    image.alpha_composite(layer, (x0, y0))
    return image


def identity(project):
    recipe_path = project / 'assets/menu-zh-cn.json'
    if not recipe_path.is_file():
        return None
    import PIL
    from PIL import features
    recipe = read_json(recipe_path)
    if recipe.get('schema') != 'tenshi-menu-zh-cn-v1':
        raise ValueError('Unsupported Chinese UI recipe')
    font = checked_path(project, recipe['font'])
    if not font.is_file():
        raise ValueError('Missing Chinese UI font')
    return {'recipe': file_record(recipe_path, 'assets/menu-zh-cn.json'),
            'font': file_record(font, recipe['font']), 'pillow': PIL.__version__,
            'freetype': features.version_module('freetype2')}


def localize(project, source, output, previews=None):
    project, source, output = Path(project).resolve(), Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError('Chinese UI transform must not overwrite its original input')
    info = identity(project)
    recipe = read_json(project / 'assets/menu-zh-cn.json')
    font = checked_path(project, recipe['font'])
    original = source.read_bytes()
    entries = {}
    for name, kind, payload in read_archive(original):
        name = name.split(b'\0', 1)[0].decode('ascii').lower()
        if name not in entries or entries[name][0] < 128 <= kind:
            entries[name] = (kind, payload)
    replacements, changes = {}, []
    for name, rules in recipe['atlases'].items():
        if name not in entries:
            raise ValueError('Missing UI atlas: ' + name)
        packed = entries[name][1]
        atlas = unpack(packed)
        frames = split_atlas(atlas)
        images, origins = {}, {}
        for rule in rules:
            for frame in rule['frames']:
                if not 0 <= frame < len(frames):
                    raise ValueError('Chinese UI frame is out of bounds')
                if frame not in images:
                    images[frame], origins[frame] = decode_image(frames[frame])
                if 'template' in rule:
                    template = rule['template']
                    if not 0 <= template < len(frames):
                        raise ValueError('Chinese UI template is out of bounds')
                    background, _ = decode_image(frames[template])
                    if background.size != images[frame].size:
                        raise ValueError('Chinese UI template dimensions differ')
                    images[frame] = background
                images[frame] = render(images[frame], rule, font)
                changes.append({'atlas': name, 'frame': frame, 'text': rule.get('text', '')})
        patches = {}
        for frame, image in images.items():
            patches[frame] = encode_image(image, origins[frame])
            if previews:
                preview_root = Path(previews)
                preview_root.mkdir(parents=True, exist_ok=True)
                # Previews are decoded output pixels, not merely the pre-encoding artwork.
                decode_image(patches[frame])[0].save(checked_path(preview_root, f'{name}-{frame}.png'))
        replacements[name] = pack(replace_frames(atlas, patches))
    result = patch_archive(original, replacements)
    if identity(project) != info:
        raise ValueError('Chinese UI recipe or font changed during rendering')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result)
    return {'locale': 'zh-CN', 'identity': info, 'input': file_record(source, 'sys.a'),
            'output': file_record(output, 'sys.a'), 'frames': len({(c['atlas'], c['frame']) for c in changes}),
            'changes': changes}
