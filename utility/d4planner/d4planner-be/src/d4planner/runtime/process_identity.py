"""Read-only migration process attribution, not an executable-name allowlist.

Opaque or inaccessible interpreter identities stay blocked. A recognizable
unrelated module/script does not become a D4Planner writer merely by using
Python/Node. This is attribution, not a claim about arbitrary program behavior.
"""
import ctypes
from datetime import datetime
import ntpath
import os
import re
import sys

_PYTHON = re.compile(r'python(?:[0-9]+(?:\.[0-9]+)*)?w?\.exe', re.ASCII)

def _interpreter(name):
    return name == 'node.exe' or _PYTHON.fullmatch(name) is not None
_NATIVE = {'d4planner.exe', 'd4planner-fe.exe'}
_SCRIPT_HOSTS = {'powershell.exe', 'pwsh.exe', 'cmd.exe', 'wscript.exe', 'cscript.exe'}
# NVDA hosts the D4Planner addon; its loaded Python addons cannot be established
# from its command line. Keep this existing capture-host guard conservative.
_CAPTURE_HOSTS = {'nvda.exe', 'nvda_nouiaccess.exe'}
_COMPONENTS = {'d4planner', 'd4planner-be', 'd4planner-hud', 'd4planner-rulekit', 'd4-rulekit'}


def windows_argv(command):
    from ctypes import wintypes as w
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(w.LPWSTR)
    kernel.LocalFree.argtypes = [w.HLOCAL]; kernel.LocalFree.restype = w.HLOCAL
    count = ctypes.c_int()
    pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not pointer:
        raise OSError('CommandLineToArgvW failed')
    try:
        return list(pointer[:count.value])
    finally:
        kernel.LocalFree(ctypes.cast(pointer, w.HLOCAL))


def _path(value):
    value = ntpath.normpath(value.replace('/', '\\'))
    if sys.platform == 'win32' and ntpath.isabs(value):
        value = os.path.realpath(value)  # Resolve existing junctions, too.
    return ntpath.normcase(value).removeprefix('\\\\?\\')


def _related_path(value, roots):
    # Text labels containing "d4planner" are not paths or identities.
    if not isinstance(value, str) or not any(c in value for c in ('/', '\\')):
        return False
    normalized = _path(value)
    if any(part.casefold() in _COMPONENTS for part in normalized.split('\\')):
        return True
    return any(normalized == root or normalized.startswith(root.rstrip('\\') + '\\') for root in roots)


def _entrypoint(argv, name):
    """Return (module/script/opaque, value), respecting interpreter options."""
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == '--':
            return ('script', argv[i + 1]) if i + 1 < len(argv) else ('opaque', '')
        if name.startswith('python'):
            if arg == '-m':
                return ('module', argv[i + 1]) if i + 1 < len(argv) else ('opaque', '')
            if arg.startswith('-m') and len(arg) > 2:
                return 'module', arg[2:]
            if arg == '-c' or arg.startswith('-c') or arg == '-':
                return 'opaque', ''
            if arg in ('-W', '-X'):
                i += 2; continue
            if arg in ('-b', '-bb', '-B', '-d', '-E', '-i', '-I', '-O', '-OO', '-P', '-q', '-s', '-S', '-u', '-v', '-vv', '-x') or arg.startswith(('-W', '-X')):
                i += 1; continue
        else:
            if arg in ('-e', '--eval', '-p', '--print', '-') or arg.startswith(('--eval=', '--print=')):
                return 'opaque', ''
            if arg in ('--require', '-r', '--import', '--loader', '--experimental-loader'):
                # Preloads can load a writer before the nominal script.
                return 'opaque', ''
            if arg in ('--no-warnings', '--enable-source-maps'):
                i += 1; continue
        if arg.startswith('-'):
            return 'opaque', ''  # Unknown option semantics are not an exemption.
        return 'script', arg
    return 'opaque', ''


def _birth(row):
    value = row.get('startedAt')
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def classify_processes(rows, *, self_pid, roots=()):
    """Return only blockers and sanitized reasons; never expose command lines."""
    roots = [_path(str(root)) for root in roots if root]
    reasons = {}; owned = set(); by_pid = {p['pid']: p for p in rows}
    for p in rows:
        pid = p['pid']; name = p['name'].casefold()
        if pid == self_pid:
            continue
        executable = p.get('executable')
        if name in _NATIVE:
            reasons[pid] = 'D4PLANNER_EXECUTABLE'; owned.add(pid); continue
        if name in _CAPTURE_HOSTS:
            reasons[pid] = 'CAPTURE_HOST_ADDONS_UNVERIFIED'; continue
        try:
            if executable and _related_path(executable, roots):
                reasons[pid] = 'D4PLANNER_PACKAGE_OR_DATA_PATH'; owned.add(pid); continue
            # An ordinary application (including the NSIS Setup parent) is
            # not a script host merely because an argument mentions DataRoot.
            # Package/native ownership above still applies to renamed workers.
            if not _interpreter(name) and name not in _SCRIPT_HOSTS:
                continue
            command = p.get('commandLine')
            if _interpreter(name) and (not executable or not ntpath.isabs(executable) or not command or _birth(p) is None
                    or type(p.get('parentPid')) is not int or p['parentPid'] < 0):
                reasons[pid] = 'INTERPRETER_IDENTITY_UNAVAILABLE'; continue
            if not command:
                continue
            argv = windows_argv(command)
            if not argv or any(not isinstance(arg, str) for arg in argv):
                raise ValueError('invalid argv')
            if _interpreter(name) and (ntpath.basename(argv[0]).casefold() != name or
                    (ntpath.isabs(argv[0]) and _path(argv[0]) != _path(executable))):
                reasons[pid] = 'INTERPRETER_IMAGE_COMMAND_MISMATCH'; continue
            if any(_related_path(arg.split('=', 1)[-1], roots) for arg in argv[1:]):
                reasons[pid] = 'D4PLANNER_ARGUMENT_PATH'; owned.add(pid); continue
            if _interpreter(name):
                kind, entry = _entrypoint(argv, name)
                if kind == 'module' and (entry.casefold() == 'd4planner' or entry.casefold().startswith('d4planner.')):
                    reasons[pid] = 'D4PLANNER_MODULE'; owned.add(pid)
                elif kind == 'script' and (_related_path(entry, roots) or ntpath.basename(entry).casefold() in ('d4planner.py', 'd4planner.pyw')):
                    reasons[pid] = 'D4PLANNER_SCRIPT'; owned.add(pid)
                elif kind == 'script' and not ntpath.isabs(entry):
                    reasons[pid] = 'INTERPRETER_WORKING_DIRECTORY_UNVERIFIED'
                elif kind == 'opaque':
                    reasons[pid] = 'INTERPRETER_ENTRYPOINT_UNVERIFIED'
        except (OSError, ValueError, TypeError):
            reasons[pid] = 'PROCESS_IDENTITY_UNVERIFIED'
    # Propagate only established D4Planner ownership, never generic Python or
    # Setup ancestry. Reject stale parent PID links using process creation time.
    changed = True
    while changed:
        changed = False
        for p in rows:
            pid = p['pid']; parent = p.get('parentPid')
            if pid == self_pid or pid in owned or parent not in owned:
                continue
            parent_birth, child_birth = _birth(by_pid[parent]), _birth(p)
            if parent_birth is not None and child_birth is not None and parent_birth > child_birth:
                continue
            reasons[pid] = ('D4PLANNER_CHILD' if parent_birth is not None and child_birth is not None
                            else 'D4PLANNER_PARENT_IDENTITY_UNVERIFIED')
            owned.add(pid); changed = True
    return ([{'pid': p['pid'], 'name': p['name']} for p in rows if p['pid'] in reasons],
            {str(pid): reason for pid, reason in reasons.items()})
