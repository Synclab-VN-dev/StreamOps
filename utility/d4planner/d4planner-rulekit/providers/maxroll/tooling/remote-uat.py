#!/usr/bin/env python3
"""Linux-only, user-owned UAT supervisor. No system install or public listener."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(state):
    return bool(state and identity(state['pid']) == state['startTime'])


def read_state(runtime):
    try:
        return json.loads((runtime / 'state.json').read_text())
    except FileNotFoundError:
        return None


def free_port(port):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def wait_for(predicate, children, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(p.poll() is not None for p in children):
            raise RuntimeError('Owned child exited; inspect private runtime logs')
        if predicate():
            return
        time.sleep(.1)
    raise TimeoutError('UAT readiness timed out')


def supervise(config_path, runtime):
    os.umask(0o077)
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_supervisor(config_path, runtime)


def run_supervisor(config_path, runtime):
    config = json.loads(config_path.read_text())
    display = int(config.get('display', 173))
    vnc, web = int(config.get('vncPort', 5903)), int(config.get('webPort', 6083))
    if not (1 <= display <= 65535 and 1024 <= vnc <= 65535 and 1024 <= web <= 65535 and vnc != web):
        raise ValueError('Invalid display or distinct unprivileged ports')
    free_port(vnc); free_port(web)
    if Path(f'/tmp/.X11-unix/X{display}').exists() or Path(f'/tmp/.X{display}-lock').exists():
        raise RuntimeError('Display occupied; refusing to touch it')
    for name in ('xvfb', 'x11vnc', 'websockify', 'novnc', 'chromium', 'snapshotRoot'):
        if not Path(config[name]).is_absolute() or not Path(config[name]).exists():
            raise ValueError(f'{name} must be an existing absolute path')
    children, logs = [], []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    env = dict(os.environ, DISPLAY=f':{display}', XAUTHORITY=str(runtime / 'Xauthority'))
    if config.get('libraryPath'):
        env['LD_LIBRARY_PATH'] = config['libraryPath']
    state = {'pid': os.getpid(), 'startTime': identity(os.getpid()), 'status': 'STARTING',
             'display': display, 'vncPort': vnc, 'webPort': web, 'children': {}}
    def spawn(name, command):
        log = (runtime / (name + '.log')).open('ab'); logs.append(log)
        child = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, start_new_session=True)
        children.append(child)
        state['children'][name] = {'pid': child.pid, 'startTime': identity(child.pid)}
        write_json(runtime / 'state.json', state)
        return child
    try:
        for stale in ('browser.json', 'browser-cleanup.json'):
            (runtime / stale).unlink(missing_ok=True)
        subprocess.run(['xauth', '-f', env['XAUTHORITY'], 'add', env['DISPLAY'], '.', secrets.token_hex(16)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        spawn('xvfb', [config['xvfb'], env['DISPLAY'], '-screen', '0', '1280x900x24',
                       '-nolisten', 'tcp', '-auth', env['XAUTHORITY']])
        wait_for(lambda: subprocess.run(['xdpyinfo', '-display', env['DISPLAY']], env=env,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0, children, 10)
        spawn('browser', ['node', str(Path(__file__).with_name('remote-uat-browser.js')), str(config_path), str(runtime)])
        wait_for(lambda: (runtime / 'browser.json').exists(), children, 60)
        spawn('vnc', [config['x11vnc'], '-display', env['DISPLAY'], '-auth', env['XAUTHORITY'],
                      '-listen', '127.0.0.1', '-rfbport', str(vnc), '-no6', '-forever', '-shared',
                      '-nopw', '-noxdamage', '-nosel', '-noclipboard', '-nosetclipboard'])
        wait_for(lambda: listening(vnc), children, 10)
        spawn('web', [config['websockify'], '--web', config['novnc'],
                      f'127.0.0.1:{web}', f'127.0.0.1:{vnc}'])
        wait_for(lambda: listening(web), children, 10)
        state['status'] = 'READY'; write_json(runtime / 'state.json', state)
        while not stopping:
            if any(p.poll() is not None for p in children):
                raise RuntimeError('Owned child exited; closing UAT session')
            time.sleep(.25)
    except BaseException as error:
        state['error'] = str(error)
        raise
    finally:
        # Stop noVNC, VNC, browser (graceful lease release), then display.
        # Process groups were created by us; never pkill or target another worker.
        for child in reversed(children):
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
        for log in logs:
            log.close()
        state['status'] = 'STOPPED'
        state['portsClosed'] = not listening(vnc) and not listening(web)
        write_json(runtime / 'state.json', state)
        (runtime / 'Xauthority').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop', '_supervise'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if args.action == '_supervise':
        return supervise(args.config.resolve(), runtime)
    state = read_state(runtime)
    if args.action == 'status':
        print(json.dumps({'running': alive(state), 'state': state}, indent=2)); return
    if args.action == 'stop':
        if alive(state):
            # pidfd prevents PID reuse between verification and signaling.
            fd = os.pidfd_open(state['pid'])
            try:
                if alive(state):
                    signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
            deadline = time.monotonic() + 75
            while alive(state) and time.monotonic() < deadline:
                time.sleep(.1)
            if alive(state):
                raise TimeoutError('Supervisor cleanup incomplete; do not kill unrelated processes')
        print(json.dumps(read_state(runtime), indent=2)); return
    if not args.config:
        parser.error('start requires --config')
    if alive(state):
        print(json.dumps(state, indent=2)); return
    os.umask(0o077)
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime / 'supervisor.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_supervise',
                                  '--config', str(args.config.resolve()), '--runtime', str(runtime)],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    def ready():
        current = read_state(runtime)
        return current and current['pid'] == child.pid and current['status'] == 'READY'
    try:
        wait_for(ready, [child], 90)
    except BaseException:
        if child.poll() is None:
            child.terminate(); child.wait(timeout=75)
        raise
    print(json.dumps(read_state(runtime), indent=2))


if __name__ == '__main__':
    main()
