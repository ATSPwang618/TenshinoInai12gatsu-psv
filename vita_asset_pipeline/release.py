"""Publish validated files as a directory transaction, retaining the previous output."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import uuid

from .common import checked_path, file_record, read_json, verify_files, write_json
from .package import DATA_FILES, MARKER


def commit_directory(staged, output, backups):
    staged, output, backups = (Path(p).resolve() for p in (staged, output, backups))
    if staged == output or staged.is_relative_to(output) or output.is_relative_to(staged):
        raise ValueError('Staging and output must be separate directories')
    backups.mkdir(parents=True, exist_ok=True)
    backup = None
    if output.exists():
        backup = backups / (output.name + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
        os.replace(output, backup)
    try:
        os.replace(staged, output)
    except OSError:
        if backup is not None:
            os.replace(backup, output)
        raise
    return backup


def publish(project, prepared, output, work, *, vpk=None, build_info=None):
    from .vpk import validate_vpk
    project, output, work = (Path(p).resolve() for p in (project, output, work))
    manifest = read_json(prepared['manifest'])
    verify_files(prepared['data'], manifest['files'], DATA_FILES, exact=True)
    package_check = validate_vpk(project, vpk, Path(prepared['data']) / 'opening.json') if vpk else None
    # Sibling staging ensures the final rename stays on the output filesystem.
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.parent / ('.' + output.name + '-' + uuid.uuid4().hex + '.partial')
    staged.mkdir()
    shutil.copytree(prepared['data'], staged / 'data')
    shutil.copyfile(prepared['manifest'], staged / MARKER)
    if vpk:
        shutil.copyfile(vpk, staged / 'tenshi-vita.vpk')
        validate_vpk(project, staged / 'tenshi-vita.vpk', staged / 'data/opening.json')
    # Preserve the user's existing plain-text installation note, not stale reports.
    note = output / '安装说明.txt'
    if note.is_file():
        shutil.copyfile(note, staged / note.name)
    verify_files(staged / 'data', manifest['files'], DATA_FILES, exact=True)
    report = {'schema': 'tenshi-build-report-v1', 'application': 'December When There Is No Angel',
              'titleId': 'TNSH00001', 'version': '00.27', 'createdUtc': datetime.now(timezone.utc).isoformat(),
              'assetCache': {'key': prepared['key'], 'hit': prepared['cacheHit']},
              'externalData': {'vitaDirectory': 'ux0:/data/tenshi/', 'files': manifest['files']},
              'build': build_info, 'vpk': package_check,
              'checks': {'dataFullSha256': True, 'vitaHardwareRun': False, 'vita3kRun': False}}
    write_json(staged / 'build-report.json', report)
    rows = [file_record(p, p.relative_to(staged).as_posix()) for p in sorted(staged.rglob('*')) if p.is_file()]
    (staged / 'SHA256SUMS.txt').write_text(''.join(row['sha256'] + '  ' + row['path'] + '\n' for row in rows), encoding='utf-8')
    backups = checked_path(work, 'backups')
    backups.mkdir(parents=True, exist_ok=True)
    if staged.stat().st_dev != backups.stat().st_dev:
        backups = output.parent / ('.' + output.name + '-backups')
    backup = commit_directory(staged, output, backups)
    print(f'Published: {output}', flush=True)
    if backup:
        print(f'Previous output retained: {backup}', flush=True)
    return report
