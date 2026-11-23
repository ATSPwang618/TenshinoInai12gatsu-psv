"""Reject SDK SDL2 variants that do not match the native GXM renderer/link profile."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


def check_backend(sdk, nm=None):
    sdk = Path(sdk).resolve()
    library = sdk / 'arm-vita-eabi/lib/libSDL2.a'
    nm = nm or sdk / 'bin/arm-vita-eabi-nm'
    if not library.is_file():
        raise ValueError(f'Missing SDL2 archive: {library}')
    symbols = []
    for mode in ('--defined-only', '--undefined-only'):
        result = subprocess.run([str(nm), mode, str(library)],
                                capture_output=True, text=True, check=True)
        symbols.append({line.split()[-1] for line in result.stdout.splitlines() if line.split()})
    if 'VITA_GXM_RenderDriver' not in symbols[0]:
        raise ValueError('SDL2 is missing VITA_GXM_RenderDriver; install the native sdl2 package')
    gl = sorted(name for name in symbols[1] if re.match(r'^(vgl\w+|egl\w+|gl[A-Z]\w*)$', name))
    if gl:
        raise ValueError('SDL2 has incompatible GL dependencies: ' + ', '.join(gl)
                         + '; reinstall native sdl2 after other SDK packages')
    return library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', default=os.environ.get('VITASDK'))
    parser.add_argument('--nm', help='symbol reader override for host regression fixtures')
    args = parser.parse_args()
    if not args.sdk:
        parser.error('--sdk or VITASDK is required')
    try:
        library = check_backend(args.sdk, args.nm)
        print(f'SDL2 native GXM backend verified (no GL dependencies): {library}')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'SDL2 backend check failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
