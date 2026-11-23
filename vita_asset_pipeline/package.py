"""Prepare unchanged archives and a validated opening in a content-addressed cache."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from .common import checked_path, file_record, read_json, validate_locations, verify_files, write_json


ARCHIVES = ('char.a', 'ed.a', 'egbg.a', 'music.a', 'se.a', 'sys.a', 'tenshi_dvd.a', 'voice.a')
MOVIE_FILES = ('opening.mp4', 'opening.idx', 'opening.json')
DATA_FILES = (*ARCHIVES, *MOVIE_FILES)
MARKER = 'data-manifest.json'


def convert_opening(project, source, output, ffmpeg, ffprobe):
    subprocess.run([sys.executable, str(project / 'tools/transcode-opening.py'), str(source / 'openning.v'),
                    '--output-dir', str(output), '--metadata', str(project / 'assets/opening.json'),
                    '--ffmpeg', ffmpeg, '--ffprobe', ffprobe], check=True)


def source_records(project, source):
    manifest = read_json(project / 'assets/game-data.json')
    if manifest.get('schema') != 'tenshi-source-v1':
        raise ValueError('Unsupported original data manifest')
    rows = manifest['files']
    verify_files(source, rows, (*ARCHIVES, 'openning.v'))
    opening = read_json(project / 'assets/opening.json')
    movie = next(row for row in rows if row['path'] == 'openning.v')
    if (movie['sha256'], movie['bytes']) != (opening['sourceSha256'], opening['sourceBytes']):
        raise ValueError('Opening recipe and original data manifest disagree')
    return rows


def prepare_data(project, source, work, ffmpeg, ffprobe, *, tool_versions):
    project, source, work = (Path(p).resolve() for p in (project, source, work))
    validate_locations(project, source, work, project / 'realease')
    print('Checking all original archives and opening (full SHA256)...', flush=True)
    rows = source_records(project, source)
    recipe = read_json(project / 'assets/opening.json')
    scripts = [project / 'tools' / name for name in ('transcode-opening.py', 'index-opening.py')]
    scripts += [project / 'vita_asset_pipeline' / name for name in ('package.py', 'common.py')]
    identity = {'schema': 'tenshi-data-cache-v1', 'source': rows, 'recipe': recipe,
                'tools': tool_versions, 'scripts': [file_record(p, p.relative_to(project).as_posix())
                                                   for p in scripts if p.is_file()]}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    cache = checked_path(work, 'cache/' + key)
    marker = cache / MARKER
    if marker.is_file():
        try:
            manifest = read_json(marker)
            if manifest['key'] != key or manifest['identity'] != identity:
                raise ValueError('Cache identity mismatch')
            verify_files(cache / 'data', manifest['files'], DATA_FILES, exact=True)
            verify_files(cache / 'data', [row for row in rows if row['path'] in ARCHIVES], ARCHIVES)
            print(f'Asset cache hit: {key[:16]} (all output hashes checked)', flush=True)
            return {'key': key, 'data': cache / 'data', 'manifest': marker, 'cacheHit': True}
        except (ValueError, OSError, KeyError, TypeError):
            print('Cache is incomplete or damaged; rebuilding without touching release.', flush=True)
    pending = checked_path(work, 'staging/assets-' + uuid.uuid4().hex)
    data = pending / 'data'
    data.mkdir(parents=True)
    for name in ARCHIVES:
        shutil.copyfile(source / name, data / name)
    convert_opening(project, source, data, ffmpeg, ffprobe)
    files = [file_record(data / name, name) for name in DATA_FILES]
    # Detect input changes during the copy, rather than attesting to mixed bytes.
    verify_files(data, [row for row in rows if row['path'] in ARCHIVES], ARCHIVES)
    manifest = {'schema': 'tenshi-data-v1', 'key': key, 'identity': identity,
                'vitaDirectory': 'ux0:/data/tenshi/', 'files': files}
    write_json(pending / MARKER, manifest)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        quarantine = checked_path(work, 'quarantine/' + key + '-' + uuid.uuid4().hex)
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        os.replace(cache, quarantine)
    os.replace(pending, cache)
    print(f'Asset cache ready: {key[:16]}', flush=True)
    return {'key': key, 'data': cache / 'data', 'manifest': marker, 'cacheHit': False}
