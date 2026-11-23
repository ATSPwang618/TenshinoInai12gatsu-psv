"""Build a program-only VPK without player data; publish to a fresh CI directory."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vita_asset_pipeline.build import build_vpk
from vita_asset_pipeline.common import file_record, overlaps, work_lock, write_json
from vita_asset_pipeline.vpk import validate_vpk


def check_output(project, output):
    project, output = Path(project).resolve(), Path(output)
    if output.is_symlink():
        raise ValueError('CI output must not be a symlink')
    output = output.resolve()
    if (output == Path(output.anchor) or
            (overlaps(project, output) and not output.is_relative_to(project / 'dist'))):
        raise ValueError('CI output must be under dist or outside project sources and player release')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('CI output must be a new or empty directory; old files are never overwritten')
    return output


def publish_ci(project, vpk, output, build_report):
    project, vpk = Path(project).resolve(), Path(vpk)
    output = check_output(project, output)
    package = validate_vpk(project, vpk)
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'tenshi-vita.vpk'
    shutil.copy2(vpk, target)
    if file_record(target) != file_record(vpk, target.name):
        raise ValueError('VPK copy failed integrity verification')
    spec = importlib.util.spec_from_file_location('tenshi_source_package', project / 'tools/package-release.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    source = output / 'tenshi-vita-source.zip'
    release.source_archive(project, source)
    report = output / 'build-report.json'
    write_json(report, {'schema': 'tenshi-ci-build-v1', 'build': build_report,
                        'package': package, 'externalDataRequired': True,
                        'files': [file_record(target), file_record(source)]})
    rows = [file_record(path) for path in (target, source, report)]
    (output / 'SHA256SUMS.txt').write_text(
        ''.join(row['sha256'] + '  ' + row['path'] + '\n' for row in rows), encoding='utf-8')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', help='existing native Linux or WSL VitaSDK path')
    parser.add_argument('--wsl', help='WSL distribution (Windows only)')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/ci')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error('--jobs must be between 1 and 32')
    try:
        output = check_output(ROOT, args.output)
        work = ROOT / '.work/ci-build'
        with work_lock(work):
            vpk, report = build_vpk(ROOT, work, sdk=args.sdk, distro=args.wsl, jobs=args.jobs)
            report['sdkImage'] = os.environ.get('CI_SDK_IMAGE')
            print(json.dumps(publish_ci(ROOT, vpk, output, report), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as error:
        print(f'CI build failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
