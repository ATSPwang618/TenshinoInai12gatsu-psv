"""Publish validated files as a directory transaction, retaining the previous output."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import uuid

from .common import checked_path, file_record, read_json, verify_files, write_json
from .package import DATA_FILES, MARKER


def _inventory(root):
    rows = []
    for item in sorted(root.rglob('*')):
        name = item.relative_to(root).as_posix()
        checked_path(root, name)
        if item.is_file():
            rows.append(file_record(item, name))
        elif not item.is_dir():
            raise ValueError(f'Unsupported release entry: {name}')
    return rows


def _atomic_copy(source, target):
    pending = target.with_name('.' + target.name + '-' + uuid.uuid4().hex + '.partial')
    try:
        shutil.copyfile(source, pending)
        if file_record(source, target.name) != file_record(pending, target.name):
            raise ValueError(f'Publication copy verification failed: {target}')
        os.replace(pending, target)
    finally:
        if pending.exists():
            pending.unlink()


def _update_busy_directory(staged, output, backup):
    previous, incoming = _inventory(output), _inventory(staged)
    if {row['path'] for row in previous} != {row['path'] for row in incoming}:
        raise ValueError('Busy output directory file set differs; refusing to overwrite user files')
    print('Output directory is busy; retaining a verified full backup before file-wise publication.', flush=True)
    shutil.copytree(output, backup)
    verify_files(backup, previous, exact=True)
    verify_files(output, previous, exact=True)
    verify_files(staged, incoming, exact=True)
    old = {row['path']: row for row in previous}
    replaced = []
    try:
        for row in incoming:
            name = row['path']
            if old[name] == row:
                continue
            # Journal before replace so cancellation cannot miss a committed file.
            replaced.append(name)
            _atomic_copy(checked_path(staged, name), checked_path(output, name))
        verify_files(output, incoming, exact=True)
    except BaseException as error:
        rollback_errors = []
        for name in reversed(replaced):
            try:
                _atomic_copy(checked_path(backup, name), checked_path(output, name))
            except Exception as rollback_error:
                rollback_errors.append(f'{name}: {rollback_error}')
        try:
            verify_files(output, previous, exact=True)
        except Exception as rollback_error:
            rollback_errors.append(str(rollback_error))
        if rollback_errors:
            raise RuntimeError(f'Publication failed; rollback incomplete. Restore from {backup}: '
                               + '; '.join(rollback_errors)) from error
        raise
    return backup


def commit_directory(staged, output, backups):
    staged, output, backups = (Path(p).resolve() for p in (staged, output, backups))
    if staged == output or staged.is_relative_to(output) or output.is_relative_to(staged):
        raise ValueError('Staging and output must be separate directories')
    if any(backups.is_relative_to(p) or p.is_relative_to(backups) for p in (staged, output)):
        raise ValueError('Backups must be separate from staging and output')
    backups.mkdir(parents=True, exist_ok=True)
    backup = None
    if output.exists():
        backup = backups / (output.name + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
        try:
            os.replace(output, backup)
        except PermissionError:
            return _update_busy_directory(staged, output, backup)
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
    if 'menuLocalization' in manifest:
        report['externalData']['menuLocalization'] = manifest['menuLocalization']
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
