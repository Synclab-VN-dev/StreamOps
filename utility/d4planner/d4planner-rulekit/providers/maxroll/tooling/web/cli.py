#!/usr/bin/env python3
"""Linux local snapshot UI lifecycle. Owns one Node server, no Chromium process."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

SERVER = Path(__file__).resolve().with_name('server.js')


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop'])
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--ssh-target', default='USER@LINUX_F', help='Used only in printed tunnel command')
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text())
    port = config['port']
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('port must be 1024..65535')
    state_dir = config_path.parent / (config_path.stem + '.runtime')
    state_dir.mkdir(mode=0o700, exist_ok=True)
    if state_dir.stat().st_uid != os.getuid() or state_dir.stat().st_mode & 0o077:
        raise ValueError('Runtime directory must be owned by current user with mode 0700')
    with (state_dir / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state_file = state_dir / 'state.json'
        state = json.loads(state_file.read_text()) if state_file.exists() else None
        alive = state and identity(state['pid']) == state['identity']
        if args.action == 'stop':
            if alive:
                # pidfd prevents signalling an unrelated process after PID reuse.
                fd = os.pidfd_open(state['pid'])
                try:
                    if identity(state['pid']) != state['identity']:
                        raise RuntimeError('Process identity changed; refusing stop')
                    signal.pidfd_send_signal(fd, signal.SIGTERM)
                    for _ in range(100):
                        if identity(state['pid']) != state['identity']:
                            break
                        time.sleep(.05)
                    else:
                        raise RuntimeError('Graceful stop did not finish; no forced kill performed')
                finally:
                    os.close(fd)
            state_file.unlink(missing_ok=True)
            print('STOPPED (owned server only)')
            return
        if args.action == 'start' and alive and state.get('config') != config:
            raise RuntimeError('Config changed while server is running; stop the owned server before restart')
        if args.action == 'status' and not alive:
            print('STOPPED')
            return
        if not alive:
            # Advisory preflight; Node bind is the final atomic conflict check.
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1', port))
            with (state_dir / 'server.log').open('w') as log:
                child = subprocess.Popen(['node', str(SERVER), '--config', str(config_path)],
                                         stdout=log, stderr=log, start_new_session=True)
            state = {'pid': child.pid, 'identity': identity(child.pid), 'port': port, 'config': config}
            state_file.write_text(json.dumps(state))
            os.chmod(state_file, 0o600)
            for _ in range(200):
                if child.poll() is not None:
                    state_file.unlink(missing_ok=True)
                    raise RuntimeError((state_dir / 'server.log').read_text()[-2000:])
                if '"ready":true' in (state_dir / 'server.log').read_text():
                    break
                time.sleep(.05)
            else:
                child.terminate()
                child.wait(timeout=10)
                state_file.unlink(missing_ok=True)
                raise RuntimeError('Startup readiness timed out')
        port = state['port']
        url = f'http://127.0.0.1:{port}/'
        # Explicit no-proxy opener, even when host environment has HTTP_PROXY.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '__local/diagnostics', timeout=3) as response:
            diag = json.load(response)
        print(json.dumps({'status': 'READY', 'pid': state['pid'], 'url': url, **diag}))
        print(f'ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:{port}:127.0.0.1:{port} {args.ssh_target}')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
