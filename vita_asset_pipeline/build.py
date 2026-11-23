"""Discover an existing native/WSL SDK and build via CMake without shell interpolation."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .common import checked_path, file_record, write_json

PROBE = r'''
import json, os, pathlib, shutil, subprocess, sys
explicit = sys.argv[1]
candidates = [explicit] if explicit else [os.environ.get('VITASDK'), '/opt/vitasdk', '/usr/local/vitasdk', str(pathlib.Path.home() / 'vitasdk')]
for candidate in candidates:
    if not candidate:
        continue
    sdk = pathlib.Path(candidate).expanduser().resolve()
    required = ['arm-vita-eabi-g++', 'vita-elf-create', 'vita-make-fself', 'vita-mksfoex', 'vita-pack-vpk']
    libs = ['SDL2', 'SDL2_image', 'SDL2_ttf', 'SDL2_mixer', 'modplug', 'xmp-lite']
    missing = [n for n in required if not (sdk / 'bin' / n).is_file()]
    missing += [n for n in libs if not (sdk / 'arm-vita-eabi/lib' / ('lib' + n + '.a')).is_file()]
    missing += [n for n in ['cmake', 'make'] if not shutil.which(n)]
    if missing or not (sdk / 'share/vita.toolchain.cmake').is_file():
        continue
    compiler = subprocess.check_output([str(sdk / 'bin/arm-vita-eabi-g++'), '--version'], text=True).splitlines()[0]
    version = sdk / 'version_info.txt'
    print(json.dumps({'sdk': str(sdk), 'compiler': compiler, 'sdkVersion': version.read_text() if version.is_file() else 'unknown', 'path': os.environ.get('PATH', '/usr/bin:/bin')}))
    sys.exit(0)
sys.exit('No complete VitaSDK found; provide --sdk and install required SDL2/media libraries separately')
'''


def capture(command):
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip() or 'Command failed: ' + str(command[0]))
    return result.stdout.decode('utf-8', errors='strict').strip()


def wsl_path(wsl, distro, path):
    return capture([wsl, '-d', distro, '--', 'wslpath', '-u', str(path).replace('\\', '/')])


def discover_sdk(distro=None, sdk=None):
    if os.name != 'nt':
        if distro:
            raise ValueError('--wsl is only used on Windows')
        info = json.loads(capture(['python3', '-c', PROBE, sdk or '']))
        return {'prefix': [], 'distro': None, **info}
    wsl = shutil.which('wsl.exe')
    if not wsl:
        raise RuntimeError('wsl.exe not found; install WSL with VitaSDK first')
    if distro:
        distros = [distro]
    else:
        result = subprocess.run([wsl, '--list', '--quiet'], capture_output=True, check=True)
        data = result.stdout
        decoded = data.decode('utf-16-le' if b'\x00' in data else 'utf-8-sig')
        distros = [line.strip().lstrip('*').strip() for line in decoded.splitlines() if line.strip()]
    errors = []
    for name in distros:
        prefix = [wsl, '-d', name, '--']
        try:
            sdk_path = wsl_path(wsl, name, sdk) if sdk and re.match(r'^[A-Za-z]:[\\/]', sdk) else sdk
            info = json.loads(capture(prefix + ['python3', '-c', PROBE, sdk_path or '']))
            return {'prefix': prefix, 'distro': name, 'wsl': wsl, **info}
        except (RuntimeError, ValueError) as error:
            errors.append(name + ': ' + str(error))
    raise RuntimeError('No usable WSL VitaSDK found. ' + '; '.join(errors))


def target_path(environment, path):
    return wsl_path(environment['wsl'], environment['distro'], Path(path).resolve()) if environment['distro'] else str(Path(path).resolve())


def run_logged(command, log):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as stream:
        stream.write('\nCOMMAND ' + json.dumps(command, ensure_ascii=False) + '\n')
        stream.flush()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace')
        for line in process.stdout:
            print(line, end='', flush=True)
            stream.write(line)
        if process.wait() != 0:
            raise RuntimeError(f'Build failed ({process.returncode}); log: {log}')


def build_vpk(project, work, opening_metadata=None, *, distro=None, sdk=None, jobs=4, environment=None):
    project, work = Path(project).resolve(), Path(work).resolve()
    env = environment or discover_sdk(distro, sdk)
    identity = {key: env[key] for key in ('distro', 'sdk', 'compiler', 'sdkVersion')}
    identity['projectPath'] = str(project)
    build_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    build = checked_path(work, 'build-vita/' + build_key)
    # Include the compiler identity in the report, not the user's full PATH.
    report = {key: env[key] for key in ('distro', 'sdk', 'compiler', 'sdkVersion')}
    report['buildType'] = 'Release'
    report['buildDirectory'] = str(build)
    report['startedUtc'] = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    log = work / 'logs' / ('build-' + stamp + '.log')
    prefix = env['prefix'] + ['env', 'VITASDK=' + env['sdk'],
                            'PATH=' + env['sdk'] + '/bin:' + env['path'], 'PYTHONUTF8=1']
    command = prefix + ['cmake', '-S', target_path(env, project), '-B', target_path(env, build),
                        '-DTENSHI_VITA=ON', '-DCMAKE_BUILD_TYPE=Release', '-DVITASDK=' + env['sdk'],
                        '-DCMAKE_TOOLCHAIN_FILE=' + env['sdk'] + '/share/vita.toolchain.cmake',
                        '-DTENSHI_OPENING_METADATA=' + target_path(env, opening_metadata or project / 'assets/opening.json')]
    print('Building with ' + (env['distro'] or 'native Linux') + ': ' + env['compiler'], flush=True)
    run_logged(command, log)
    run_logged(prefix + ['cmake', '--build', target_path(env, build), '--parallel', str(jobs)], log)
    vpk = build / 'tenshi-vita.vpk'
    if not vpk.is_file():
        raise RuntimeError('CMake returned success but no VPK was produced')
    report['finishedUtc'] = datetime.now(timezone.utc).isoformat()
    report['log'] = str(log)
    report['vpk'] = file_record(vpk)
    for field, command in (('sourceBaseCommit', ['git', '-C', str(project), 'rev-parse', 'HEAD']),
                           ('sourceStatus', ['git', '-C', str(project), 'status', '--short'])):
        try:
            report[field] = capture(command)
        except (RuntimeError, OSError):
            report[field] = 'unavailable'
    write_json(work / 'last-build.json', report)
    return vpk, report
