"""Check a program-only VPK; optionally archive sources without generating MD files."""
import argparse
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vita_asset_pipeline.common import file_record
from vita_asset_pipeline.vpk import validate_vpk


def source_archive(project, output):
    allowed = []
    for folder in ('src', 'tests', 'tools', 'vita_asset_pipeline', 'licenses', 'third_party', 'sce_sys'):
        allowed.extend(p for p in (project / folder).rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    allowed.extend(p for p in (project / 'prepare').iterdir()
                   if p.is_file() and (p.name.endswith('.cs.in') or p.suffix == '.csproj'))
    allowed.extend(project / name for name in ('assets/opening.json', 'assets/game-data.json',
        'assets/SourceHanSansCN-Regular.otf', 'assets/source-han-sans.json'))
    allowed.extend(p for p in project.iterdir() if p.is_file() and
                   (p.suffix == '.md' or p.name in ('LICENSE', 'CMakeLists.txt', '.gitignore',
                    '.gdignore', '.clang-format', 'prepare-tenshi-vita.py')))
    pending = output.with_suffix('.zip.partial')
    with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(allowed)):
            source_suffixes = {'.cpp', '.c', '.h', '.hpp', '.inc', '.py', '.ps1', '.json',
                               '.png', '.xml', '.txt', '.md', '.ijg', '.in', '.csproj'}
            if (path.is_file() and not path.is_symlink()
                    and path.resolve().is_relative_to(project.resolve())
                    and (path.suffix.lower() in source_suffixes or path.relative_to(project).as_posix() in
                         ('assets/SourceHanSansCN-Regular.otf', 'third_party/pthread-embedded-63e1cd9.zip') or path.name in
                         ('LICENSE', 'CMakeLists.txt', '.gitignore', '.gdignore', '.clang-format'))):
                archive.write(path, path.relative_to(project).as_posix())
    pending.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vpk', type=Path, help='VPK to validate (default: OUTPUT/tenshi-vita.vpk)')
    parser.add_argument('--output', type=Path, default=ROOT / 'realease')
    parser.add_argument('--opening-metadata', type=Path, help='metadata used for this specific build')
    parser.add_argument('--source-archive', action='store_true', help='also write a code/font/shell source ZIP, never game data')
    args = parser.parse_args()
    vpk = args.vpk or args.output / 'tenshi-vita.vpk'
    try:
        metadata = args.opening_metadata
        paired_metadata = vpk.parent / 'data/opening.json'
        if metadata is None and paired_metadata.is_file():
            metadata = paired_metadata
        result = validate_vpk(ROOT, vpk, metadata)
        if args.source_archive:
            args.output.mkdir(parents=True, exist_ok=True)
            source = args.output / 'tenshi-vita-source.zip'
            source_archive(ROOT, source)
            result['sourceArchive'] = file_record(source)
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f'Package validation failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
