"""Find existing tools without changing PATH, installing packages or downloading."""
import os
from pathlib import Path
import shutil
import subprocess


def tool_path(explicit, name):
    candidates = [explicit] if explicit else [shutil.which(name)]
    if not explicit and os.name == 'nt':
        candidates.append(str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'ffmpeg/bin' / (name + '.exe')))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
        if candidate and shutil.which(candidate):
            return shutil.which(candidate)
    raise RuntimeError(f'{name} not found; provide --{name} with its executable path')


def media_tools(ffmpeg=None, ffprobe=None):
    ffmpeg = tool_path(ffmpeg, 'ffmpeg')
    if not ffprobe:
        sibling = Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
        ffprobe = str(sibling) if sibling.is_file() else None
    ffprobe = tool_path(ffprobe, 'ffprobe')
    versions = {name: subprocess.check_output([path, '-version'], text=True, encoding='utf-8').splitlines()[0]
                for name, path in (('ffmpeg', ffmpeg), ('ffprobe', ffprobe))}
    encoders = subprocess.check_output([ffmpeg, '-hide_banner', '-encoders'], text=True, encoding='utf-8', stderr=subprocess.STDOUT)
    if 'libx264' not in encoders:
        raise RuntimeError('FFmpeg must include libx264')
    return ffmpeg, ffprobe, versions
