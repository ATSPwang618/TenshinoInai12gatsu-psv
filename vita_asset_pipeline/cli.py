"""Prepare external Tenshi data and optionally build/publish the matching Vita VPK."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from .build import build_vpk, discover_sdk
from .common import read_json, validate_locations, work_lock, write_json
from .dependencies import media_tools
from .package import prepare_data, source_records
from .release import publish


def main(default_project=None, *, build_default=False):
    project = Path(default_project or Path(__file__).resolve().parents[1]).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', type=Path, help='original local PC game directory')
    parser.add_argument('--source', type=Path, help='same as input; remembered locally after successful preparation')
    parser.add_argument('--output', type=Path, help='final directory (default: PROJECT/realease)')
    parser.add_argument('--work-dir', type=Path, help='cache/build/log directory (default: PROJECT/.work)')
    parser.add_argument('--ffmpeg', help='existing FFmpeg executable with libx264')
    parser.add_argument('--ffprobe', help='existing ffprobe executable')
    parser.add_argument('--build', action='store_true', default=build_default, help='also build, validate and publish a matching VPK')
    parser.add_argument('--check', action='store_true', help='read-only source/tool/SDK validation; no cache, build or publication')
    parser.add_argument('--wsl', help='WSL distribution (automatically discover a usable SDK otherwise)')
    parser.add_argument('--sdk', help='existing VitaSDK directory inside WSL/Linux')
    parser.add_argument('--jobs', type=int, default=4, help='CMake parallel compiler jobs, 1..32 (default: 4)')
    args = parser.parse_args()
    if args.input and args.source:
        parser.error('use input or --source, not both')
    if not 1 <= args.jobs <= 32:
        parser.error('--jobs must be between 1 and 32')
    try:
        work = (args.work_dir or project / '.work').resolve()
        output = (args.output or project / 'realease').resolve()
        settings_path = work / 'local.json'
        settings = read_json(settings_path) if settings_path.is_file() else {}
        source = args.input or args.source or settings.get('source')
        if not source:
            raise ValueError('Provide the original game directory using --source (or the positional input) on the first run')
        source = Path(source).resolve(strict=True)
        if not source.is_dir():
            raise ValueError('The original resource input must be a directory')
        validate_locations(project, source, work, output)
        if not args.check and not args.build and (output / 'tenshi-vita.vpk').exists():
            raise ValueError('A VPK already exists in this output; use --build for a matching full release or choose another --output')
        ffmpeg, ffprobe, versions = media_tools(args.ffmpeg or settings.get('ffmpeg'), args.ffprobe or settings.get('ffprobe'))
        distro, sdk = args.wsl or settings.get('wsl'), args.sdk or settings.get('sdk')
        environment = discover_sdk(distro, sdk) if args.build else None
        if args.check:
            rows = source_records(project, source)
            print(json.dumps({'source': str(source), 'originalFilesChecked': len(rows), 'tools': versions,
                              'wsl': environment['distro'] if environment else None,
                              'sdk': environment['sdk'] if environment else None,
                              'readOnly': True}, ensure_ascii=False, indent=2))
            return 0
        with work_lock(work):
            prepared = prepare_data(project, source, work, ffmpeg, ffprobe, tool_versions=versions)
            vpk, info = (build_vpk(project, work, Path(prepared['data']) / 'opening.json',
                                  jobs=args.jobs, environment=environment) if args.build else (None, None))
            report = publish(project, prepared, output, work, vpk=vpk, build_info=info)
            write_json(settings_path, {'source': str(source), 'ffmpeg': ffmpeg, 'ffprobe': ffprobe,
                                      'wsl': environment['distro'] if environment else distro,
                                      'sdk': environment['sdk'] if environment else sdk})
            write_json(work / 'last-run.json', {'output': str(output), 'assetCache': report['assetCache'],
                                              'vpk': report['vpk']})
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f'Pipeline failed: {error}', file=sys.stderr)
        return 1
