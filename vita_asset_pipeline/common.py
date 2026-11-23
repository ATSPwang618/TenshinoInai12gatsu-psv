"""Streaming integrity checks, safe paths and a single-writer work lock."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import uuid


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(pending, path)


def file_record(path, name=None):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': name or path.name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def checked_path(root, name):
    pure = PurePosixPath(name)
    if (not name or name == '.' or pure.is_absolute() or '..' in pure.parts
            or ':' in name or '\\' in name or pure.as_posix() != name):
        raise ValueError(f'Unsafe relative path: {name!r}')
    target = Path(root) / pure
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError(f'Path escapes its directory: {name}')
    if target.is_symlink():
        raise ValueError(f'Symlink is not a resource file: {name}')
    return target


def verify_files(root, rows, expected=None, *, exact=False):
    names = [row['path'] for row in rows]
    if len(names) != len(set(names)) or (expected is not None and set(names) != set(expected)):
        raise ValueError('Manifest file set differs from required resources')
    if exact:
        items = list(Path(root).rglob('*'))
        for item in items:
            checked_path(root, item.relative_to(root).as_posix())
        actual = {p.relative_to(root).as_posix() for p in items if p.is_file()}
        if actual != set(names):
            raise ValueError('Output contains unlisted or missing resource files')
    for row in rows:
        target = checked_path(root, row['path'])
        if not target.is_file() or file_record(target, row['path']) != row:
            raise ValueError(f'Resource missing or SHA256/size mismatch: {target}')


def overlaps(first, second):
    first, second = Path(first).resolve(), Path(second).resolve()
    return first.is_relative_to(second) or second.is_relative_to(first)


def validate_locations(project, source, work, output):
    project, source, work, output = (Path(p).resolve() for p in (project, source, work, output))
    for target, managed in ((work, project / '.work'), (output, project / 'realease')):
        if overlaps(target, project) and target != managed:
            raise ValueError(f'Output must not overlap project sources: {target}')
        if overlaps(target, source):
            raise ValueError(f'Output must not overlap original resources: {target}')
        if target == Path(target.anchor):
            raise ValueError('A filesystem root cannot be an output')
    if overlaps(work, output):
        raise ValueError('Work and release directories must not overlap')


@contextmanager
def work_lock(work):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    lock = work / 'pipeline.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError(f'Another build owns {lock}; inspect its PID before removing a stale lock') from error
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(str(os.getpid()) + '\n')
        yield
    finally:
        lock.unlink()
