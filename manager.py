"""Opt-in Windows one-shot jobs and conservative Codex lifecycle hooks.

Only a declared one-shot command is assigned to a NEW job. No existing process
is ever enrolled; maintenance never kills by executable name or bare PID.
"""
import argparse
import base64
import ctypes as C
from ctypes import wintypes as W
import datetime as D
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib
import uuid

BASE = Path(__file__).resolve().parent
CATALOG = BASE / 'catalog'
EVENTS = BASE / 'events'
PWSH = Path(os.environ.get('CODEX_LIFECYCLE_PWSH') or shutil.which('pwsh') or
    Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe')
PROTECTED = re.compile(r'(?<![a-z])(?:research|training)(?![a-z])|\b(?:ssh|scp|sftp|wsl|uvx|uv|blender|ffmpeg|aria2c|wstunnel|node_repl|codex)\.exe\b|(?<![\w\\/:.-])(?:ssh|scp|sftp|wsl|uvx|uv|blender|ffmpeg|aria2c|wstunnel|node_repl|codex)(?=\s|$)|\bmcp\b|blender-mcp|\b(?:train|training|research|render|serve|server|download|nohup|persistent)\b', re.I)
K = C.WinDLL('kernel32', use_last_error=True)


class Basic(C.Structure):
    _fields_ = [('PerProcessUserTimeLimit', C.c_longlong), ('PerJobUserTimeLimit', C.c_longlong),
        ('LimitFlags', W.DWORD), ('MinimumWorkingSetSize', C.c_size_t),
        ('MaximumWorkingSetSize', C.c_size_t), ('ActiveProcessLimit', W.DWORD),
        ('Affinity', C.c_size_t), ('PriorityClass', W.DWORD), ('SchedulingClass', W.DWORD)]


class IO(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount',
        'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class Extended(C.Structure):
    _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', C.c_size_t),
        ('JobMemoryLimit', C.c_size_t), ('PeakProcessMemoryUsed', C.c_size_t), ('PeakJobMemoryUsed', C.c_size_t)]


class Startup(C.Structure):
    _fields_ = [('cb', W.DWORD), ('lpReserved', W.LPWSTR), ('lpDesktop', W.LPWSTR),
        ('lpTitle', W.LPWSTR), ('dwX', W.DWORD), ('dwY', W.DWORD), ('dwXSize', W.DWORD),
        ('dwYSize', W.DWORD), ('dwXCountChars', W.DWORD), ('dwYCountChars', W.DWORD),
        ('dwFillAttribute', W.DWORD), ('dwFlags', W.DWORD), ('wShowWindow', W.WORD),
        ('cbReserved2', W.WORD), ('lpReserved2', C.POINTER(C.c_ubyte)),
        ('hStdInput', W.HANDLE), ('hStdOutput', W.HANDLE), ('hStdError', W.HANDLE)]


class ProcessInfo(C.Structure):
    _fields_ = [('hProcess', W.HANDLE), ('hThread', W.HANDLE), ('dwProcessId', W.DWORD), ('dwThreadId', W.DWORD)]


def api(name, result, args):
    fn = getattr(K, name)
    fn.restype, fn.argtypes = result, args
    return fn


CreateJob = api('CreateJobObjectW', W.HANDLE, [C.c_void_p, W.LPCWSTR])
OpenJob = api('OpenJobObjectW', W.HANDLE, [W.DWORD, W.BOOL, W.LPCWSTR])
SetJob = api('SetInformationJobObject', W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD])
QueryJob = api('QueryInformationJobObject', W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p])
AssignJob = api('AssignProcessToJobObject', W.BOOL, [W.HANDLE, W.HANDLE])
TerminateJob = api('TerminateJobObject', W.BOOL, [W.HANDLE, W.UINT])
Close = api('CloseHandle', W.BOOL, [W.HANDLE])
CreateProcess = api('CreateProcessW', W.BOOL, [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p,
    W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR, C.POINTER(Startup), C.POINTER(ProcessInfo)])
Resume = api('ResumeThread', W.DWORD, [W.HANDLE])
Wait = api('WaitForSingleObject', W.DWORD, [W.HANDLE, W.DWORD])
ExitCode = api('GetExitCodeProcess', W.BOOL, [W.HANDLE, C.POINTER(W.DWORD)])
OpenProcess = api('OpenProcess', W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])
Times = api('GetProcessTimes', W.BOOL, [W.HANDLE, C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME)])
StdHandle = api('GetStdHandle', W.HANDLE, [W.DWORD])
Inherit = api('SetHandleInformation', W.BOOL, [W.HANDLE, W.DWORD, W.DWORD])


def check(ok):
    if not ok:
        raise C.WinError(C.get_last_error())


def utc():
    return D.datetime.now(D.timezone.utc).isoformat()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def event(data):
    name = uuid.uuid4().hex + '.json'
    value = dict(checked_utc=utc(), **data)
    try:
        write(EVENTS / name, value)
    except PermissionError:
        # A direct caller may be sandboxed to another workspace.
        write(Path.cwd() / '.codex-process-lifecycle' / 'events' / name, value)


def birth(pid):
    """Creation FILETIME of a live process; denied access raises, never means dead."""
    h = OpenProcess(0x1000 | 0x100000, False, int(pid))
    if not h:
        if C.get_last_error() in (87, 1168):
            return None
        raise C.WinError(C.get_last_error())
    try:
        if Wait(h, 0) == 0:
            return None
        values = [W.FILETIME() for _ in range(4)]
        check(Times(h, *[C.byref(v) for v in values]))
        return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
    finally:
        Close(h)


def prepare(data):
    specific = {'hookEventName': 'PreToolUse'}
    result = {'hookSpecificOutput': specific}
    inp = data.get('tool_input', {})
    command = inp.get('command', '')
    if not isinstance(command, str) or data.get('tool_name') != 'Bash':
        return result
    if str(BASE / 'Invoke-OneShot.ps1').lower() in command.lower():
        specific['additionalContext'] = 'Direct one-shot entry already owns its dedicated job; do not wrap twice.'
        return result
    marker = re.match(r'^\s*#\s*codex-lifecycle:\s*oneshot\s*\r?\n', command, re.I)
    if not marker or PROTECTED.search(command[marker.end():]) or inp.get('tty'):
        specific['additionalContext'] = ('Process lifecycle: persistent, research, SSH, service, interactive or unmarked command is retained. Declare only finite local commands with a first line # codex-lifecycle: oneshot; never mark a background task as one-shot.')
        event({'event': 'pre', 'session_id': data.get('session_id'), 'decision': 'protected_or_unmarked'})
        return result
    workdir = Path(inp.get('workdir') or data.get('cwd') or '').resolve()
    if not workdir.is_dir():
        raise ValueError('One-shot requires an existing working directory')
    run_id = uuid.uuid4().hex
    record_path = workdir / '.codex-process-lifecycle' / (run_id + '.json')
    payload = command[marker.end():]
    record = {'schema': 1, 'kind': 'oneshot', 'run_id': run_id,
        'job_name': 'Local\\CodexOneShot_' + run_id, 'state': 'pending',
        'session_id': data.get('session_id'), 'tool_use_id': data.get('tool_use_id'),
        'created_utc': utc(), 'cwd': str(workdir), 'command': payload,
        'command_sha256': hashlib.sha256(payload.encode()).hexdigest()}
    write(record_path, record)
    try:
        write(CATALOG / (run_id + '.json'), {'record_path': str(record_path), 'session_id': data.get('session_id')})
    except PermissionError:
        # The local registration remains authoritative; global maintenance can
        # discover it under configured workspace roots without extra permissions.
        pass
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    rewritten = '& ' + quote(sys.executable) + ' ' + quote(BASE / 'manager.py') + ' run --record ' + quote(record_path) + '\nexit $LASTEXITCODE'
    specific.update({'permissionDecision': 'allow', 'updatedInput': {'command': rewritten}})
    result['record_path'] = str(record_path)
    event({'event': 'pre', 'run_id': run_id, 'session_id': data.get('session_id'), 'decision': 'wrapped_oneshot'})
    return result


def validate(record):
    rid = record.get('run_id', '')
    if record.get('schema') != 1 or record.get('kind') != 'oneshot' or not re.fullmatch('[0-9a-f]{32}', rid):
        raise ValueError('Invalid one-shot registration')
    if record.get('job_name') != 'Local\\CodexOneShot_' + rid:
        raise ValueError('Job identity differs from registration')
    if hashlib.sha256(record['command'].encode()).hexdigest() != record['command_sha256']:
        raise ValueError('Registered command changed')


def run(record_path):
    path = Path(record_path)
    record = json.loads(path.read_text(encoding='utf-8'))
    validate(record)
    if record['state'] != 'pending' or PROTECTED.search(record['command']):
        raise ValueError('Only pending, unprotected one-shot commands may be launched')
    # Hook input may contain only the session cwd, omitting exec's workdir override.
    # The wrapper is already launched in the tool's effective working directory.
    record.update(state='starting', manager_pid=os.getpid(), manager_birth=birth(os.getpid()), execution_cwd=os.getcwd())
    write(path, record)
    job, pi = None, ProcessInfo()
    assigned = False
    try:
        job = CreateJob(None, record['job_name'])
        check(job)
        if C.get_last_error() == 183:
            raise ValueError('Refusing an already existing job')
        limit = Extended()
        limit.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway
        check(SetJob(job, 9, C.byref(limit), C.sizeof(limit)))
        si = Startup()
        si.cb, si.dwFlags = C.sizeof(si), 0x100
        for attr, kind in [('hStdInput', -10), ('hStdOutput', -11), ('hStdError', -12)]:
            handle = StdHandle(kind & 0xffffffff)
            setattr(si, attr, handle)
            if handle and handle != C.c_void_p(-1).value:
                check(Inherit(handle, 1, 1))
        script = '[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n' + record['command']
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        command_line = subprocess.list2cmdline([str(PWSH), '-NoLogo', '-NoProfile', '-EncodedCommand', encoded])
        # Suspended creation prevents children escaping before job assignment.
        check(CreateProcess(str(PWSH), C.create_unicode_buffer(command_line), None, None,
            True, 0x4 | 0x08000000, None, record['execution_cwd'], C.byref(si), C.byref(pi)))
        check(AssignJob(job, pi.hProcess))
        assigned = True
        record.update(state='running', root_pid=pi.dwProcessId, root_birth=birth(pi.dwProcessId), started_utc=utc())
        write(path, record)
        if Resume(pi.hThread) == 0xffffffff:
            raise C.WinError(C.get_last_error())
        Close(pi.hThread)
        pi.hThread = None
        while True:
            status = Wait(pi.hProcess, 200)
            if status == 0:
                break
            if status != 258:
                raise C.WinError(C.get_last_error())
        code = W.DWORD()
        check(ExitCode(pi.hProcess, C.byref(code)))
        # Closing the sole job handle reclaims any remaining associated children.
        check(Close(job))
        job = None
        record.update(state='completed', exit_code=code.value, completed_utc=utc(), reclaim='job_last_handle_closed')
        write(path, record)
        return code.value
    except BaseException as exc:
        record.update(state='error', error=str(exc), completed_utc=utc())
        write(path, record)
        raise
    finally:
        if job:
            Close(job)
        if pi.hThread:
            # A suspended child that could not be assigned never executed user code.
            if not assigned and pi.hProcess:
                terminate = api('TerminateProcess', W.BOOL, [W.HANDLE, W.UINT])
                terminate(pi.hProcess, 1)
            Close(pi.hThread)
        if pi.hProcess:
            Close(pi.hProcess)


def sweep_record(path):
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    validate(record)
    result = {'run_id': record['run_id'], 'decision': 'keep_pending'}
    if record['state'] == 'pending':
        return result
    if record.get('manager_pid'):
        current = birth(record['manager_pid'])
        if current is not None:
            result['decision'] = 'keep_running' if current == record.get('manager_birth') else 'skip_identity_changed'
            return result
    # Never stop a bare PID: only open this registration's random dedicated job.
    job = OpenJob(0x4 | 0x8, False, record['job_name'])
    if not job:
        if C.get_last_error() not in (2, 3):
            raise C.WinError(C.get_last_error())
        result['decision'] = 'job_already_absent'
        return result
    try:
        limit = Extended()
        check(QueryJob(job, 9, C.byref(limit), C.sizeof(limit), None))
        flags = limit.BasicLimitInformation.LimitFlags
        if flags & 0x2000 == 0 or flags & (0x800 | 0x1000):
            result['decision'] = 'skip_unexpected_job_limits'
            return result
        # Repeat owner identity immediately before changing this dedicated job.
        if record.get('manager_pid') and birth(record['manager_pid']) is not None:
            result['decision'] = 'keep_owner_reappeared'
            return result
        check(TerminateJob(job, 1))
        result['decision'] = 'reclaimed_orphan_job'
        return result
    finally:
        Close(job)


def sweep(session=None):
    results = []
    paths = set()
    for item in CATALOG.glob('*.json'):
        try:
            entry = json.loads(item.read_text(encoding='utf-8'))
            if session and entry.get('session_id') != session:
                continue
            paths.add(Path(entry['record_path']).resolve())
        except Exception as exc:
            results.append({'decision': 'skip_error', 'error': str(exc), 'catalog': item.name})
    # Discover direct-entry registrations when the caller could not update the
    # shared catalog. Inspect only configured project roots, never a disk crawl.
    config_path = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'
    config = tomllib.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    for root in [Path.cwd(), *[Path(p) for p in config.get('projects', {})]]:
        paths.update(p.resolve() for p in (root / '.codex-process-lifecycle').glob('*.json'))
    for path in paths:
        try:
            if session:
                record = json.loads(path.read_text(encoding='utf-8'))
                if record.get('session_id') != session:
                    continue
            results.append(sweep_record(path))
        except Exception as exc:
            results.append({'decision':'skip_error', 'error':str(exc), 'record':str(path)})
    event({'event': 'sweep', 'session_id': session, 'results': results})
    return results


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pre', 'maintenance', 'run', 'sweep', 'execute'])
    parser.add_argument('--record')
    args = parser.parse_args()
    if args.mode == 'run':
        return run(args.record)
    if args.mode == 'sweep':
        print(json.dumps({'results': sweep()}, ensure_ascii=False))
        return 0
    data = json.load(sys.stdin)
    if args.mode == 'execute':
        result = prepare(data)
        if 'record_path' not in result:
            raise ValueError('Direct one-shot entry rejected a protected or unmarked command; use its persistent lifecycle')
        return run(result['record_path'])
    if args.mode == 'pre':
        result = prepare(data)
        result.pop('record_path', None)
        print(json.dumps(result, ensure_ascii=False))
    else:
        results = sweep(data.get('session_id'))
        event({'event': data.get('hook_event_name'), 'session_id': data.get('session_id'), 'decisions': results})
        print('{}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('Codex process lifecycle: ' + str(exc), file=sys.stderr)
        sys.exit(1)
