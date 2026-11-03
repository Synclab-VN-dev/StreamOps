#!/usr/bin/env python3
"""Owned loopback UI lifecycle with validated capture selection and recoverable activation."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from capture_state import State, atomic, eligible, locked, private_dir

SERVER = Path(__file__).resolve().with_name('server.js')
CHECK = SERVER.with_name('activation-check.js')
CHILDREN = {}


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


def runtime_state(directory):
    file = directory / 'state.json'
    return json.loads(file.read_text()) if file.exists() else None


def owned_alive(state):
    if not state or not state.get('identity') or identity(state['pid']) != state['identity']:
        return False
    argv = Path(f"/proc/{state['pid']}/cmdline").read_bytes().decode().strip('\0').split('\0')
    # Covers legacy state files too, but never trusts PID/start time alone.
    if len(argv) != 4 or Path(argv[1]).resolve() != SERVER or argv[2] != '--config':
        raise RuntimeError('Process command ownership mismatch; refusing signal/reuse')
    if json.loads(Path(argv[3]).read_text()) != state['config']:
        raise RuntimeError('Process configuration ownership mismatch; refusing signal/reuse')
    return True


def stop_owned(directory):
    state = runtime_state(directory)
    if owned_alive(state):
        fd = os.pidfd_open(state['pid'])
        try:
            if identity(state['pid']) != state['identity']:
                raise RuntimeError('Process identity changed; refusing stop')
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            for _ in range(200):
                if identity(state['pid']) != state['identity']:
                    break
                time.sleep(.05)
            else:
                raise RuntimeError('Graceful stop did not finish; no forced kill performed')
        finally:
            os.close(fd)
    (directory / 'state.json').unlink(missing_ok=True)
    if state and state['pid'] in CHILDREN:
        CHILDREN.pop(state['pid']).wait(timeout=10)


def diagnostic(state):
    if not owned_alive(state):
        raise RuntimeError('Owned server is not running')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{state['port']}/"
    with opener.open(url + '__local/diagnostics', timeout=5) as response:
        result = json.load(response)
    if (result['snapshotId'] != state['config']['snapshotId'] or
            result.get('manifestSha256') not in (None, state['config']['manifestSha256'])):
        raise RuntimeError('Runtime snapshot mismatch')
    return {'status': 'READY', 'pid': state['pid'], 'url': url, **result}


def start_owned(directory, config, config_path=None):
    state = runtime_state(directory)
    if owned_alive(state):
        if state['config'] != config:
            raise RuntimeError('Config changed while server is running; owned transition required')
        return diagnostic(state)
    port = config['port']
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('port must be 1024..65535')
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', port))
    if config_path is None:
        config_path = directory / 'process-config.json'
        atomic(config_path, config)
    with (directory / 'server.log').open('w') as log:
        child = subprocess.Popen(['node', str(SERVER), '--config', str(config_path)],
                                 stdout=log, stderr=log, start_new_session=True,
                                 env={**os.environ, 'LOCAL_UI_OWNER_STATE': str(directory / 'state.json')})
    state = {'pid': child.pid, 'identity': identity(child.pid), 'port': port, 'config': config}
    CHILDREN[child.pid] = child
    atomic(directory / 'state.json', state)
    try:
        for _ in range(400):
            if child.poll() is not None:
                raise RuntimeError((directory / 'server.log').read_text()[-2000:])
            if '"ready":true' in (directory / 'server.log').read_text():
                return diagnostic(state)
            time.sleep(.05)
        raise RuntimeError('Startup readiness timed out')
    except BaseException:
        stop_owned(directory)
        raise


def check(config, directory, kind='verify'):
    filename = directory / (kind + '-config.json')
    atomic(filename, config)
    with (directory / (kind + '.log')).open('w') as log:
        result = subprocess.run(['node', str(CHECK), kind, str(filename)], stdout=log, stderr=log, timeout=180)
    if result.returncode:
        raise RuntimeError(f'Candidate {kind} failed; see {directory / (kind + ".log")}')


def isolated_probe(config, settings, directory):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    probe_dir = private_dir(directory / 'probe-runtime')
    try:
        start_owned(probe_dir, {**config, 'port': port})
        check({**config, 'chromium': settings['chromium'], 'url': f'http://127.0.0.1:{port}/',
               'evidenceDir': str(directory / 'native-health')}, directory, 'health')
    finally:
        stop_owned(probe_dir)


def server_config(package, port):
    return {**{key: package['config'][key] for key in ('snapshotRoot', 'snapshotId', 'manifestSha256', 'uiTrust')}, 'port': port}


def managed(action, settings, directory, *, verifier=check, probe=isolated_probe, starter=start_owned):
    db = State(settings['stateRoot'])
    data = db.command({'operation': 'read'})
    runtime = runtime_state(directory)
    # One-time adoption of the existing validated, CLI-owned server. No calculated compatibility is created.
    if not data['activeUi'] and not data['transition'] and owned_alive(runtime):
        config = runtime['config']
        verifier(config, directory)
        manifest = json.loads((Path(config['snapshotRoot']) / config['snapshotId'] / 'manifest.json').read_text())
        package = {'snapshotId': config['snapshotId'], 'snapshotRoot': config['snapshotRoot'], 'kind': 'ui',
                   'mode': 'ui', 'runId': 'adopted', 'capturedAt': manifest['capturedAt'], 'validationStatus': 'VALIDATED',
                   'manifestSha256': config['manifestSha256'], 'coverageSha256': config['uiTrust']['coverageSha256'],
                   'validationSha256': config['uiTrust']['validationSha256'], 'config': config, 'relatedSnapshots': []}
        data = db.command({'operation': 'adopt', 'package': package})
    if action == 'status':
        result = diagnostic(runtime) if owned_alive(runtime) else {'status': 'STOPPED'}
        candidate = eligible(data)
        return {**result, 'activeUi': data['activeUi'], 'previousActiveUi': data['previousActiveUi'],
                'candidateUi': candidate['snapshotId'] if candidate else None, 'transition': data['transition'],
                'snapshots': [{'snapshotId': p['snapshotId'], 'kind': p['kind'], 'runId': p['runId'],
                               'validationStatus': p['validationStatus'],
                               'status': 'ACTIVE' if p['snapshotId'] == data['activeUi'] else
                               'PREVIOUS_ACTIVE' if p['snapshotId'] == data['previousActiveUi'] else p['validationStatus'],
                               'activationRejected': p.get('activationRejected', False)} for p in data['packages'].values()],
                'captureRuns': list(data['runs'].values())[-10:]}
    if action == 'stop':
        stop_owned(directory)
        return {'status': 'STOPPED', 'activeUi': data['activeUi']}

    def restore(transition):
        stop_owned(directory)
        if transition['oldId']:
            old = server_config(data['packages'][transition['oldId']], settings['web']['port'])
            verifier(old, directory)
            starter(directory, old)
        db.command({'operation': 'abort'})

    if data['transition']:
        # Crash recovery always restores the committed selection, even if the new process was started.
        restore(data['transition'])
        raise RuntimeError('Interrupted activation rolled back to committed selection; retry start')
    target = data['packages'].get(data['previousActiveUi']) if action == 'rollback' else eligible(data)
    if not target:
        raise RuntimeError('No validated UI candidate/previous selection available; capture --mode ui first')
    config = server_config(target, settings['web']['port'])
    if target['snapshotId'] == data['activeUi']:
        return starter(directory, config)
    print('Switching UI package may require reload and discard unexported tab edits. Old tabs cannot relabel builds.', file=sys.stderr)
    # Preflight port/process ownership before any interruption. Probe binds its own free port.
    if owned_alive(runtime):
        diagnostic(runtime)
        if runtime['config']['snapshotId'] != data['activeUi']:
            raise RuntimeError('Running snapshot differs from committed selection')
    else:
        with socket.socket() as test:
            test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test.bind(('127.0.0.1', settings['web']['port']))
    transaction_dir = private_dir(Path(settings['stateRoot']) / 'activation' / (str(time.time_ns())))
    verifier(config, transaction_dir)
    probe(config, settings, transaction_dir)
    data = db.command({'operation': 'prepare', 'oldId': data['activeUi'], 'targetId': target['snapshotId'], 'action': action})
    transition = data['transition']
    try:
        stop_owned(directory)
        result = starter(directory, config)
        if result.get('manifestSha256') != config['manifestSha256']:
            raise RuntimeError('New server manifest verification failed')
        db.command({'operation': 'commit', 'transition': transition})
        return {**result, 'activeUi': target['snapshotId'], 'previousActiveUi': transition['oldId']}
    except BaseException:
        restore(transition)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop', 'rollback'])
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('MAXROLL_CAPTURE_CONFIG', str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'streamops/maxroll-capture.json'))))
    parser.add_argument('--ssh-target', default=None)
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text())
    managed_mode = config.get('schemaVersion') == 'maxroll-capture-config/v1'
    if managed_mode:
        stat = config_path.stat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise ValueError('Private config must be owned, mode 0600')
        directory = private_dir(config['web'].get('runtimeDir', str(Path(config['stateRoot']) / 'web.runtime')))
        if not config.get('chromium'):
            result = subprocess.check_output(['node', '-e', 'process.stdout.write(require(process.argv[1]).discoverBrowser(process.env)||"")', str(SERVER.parents[2] / 'src/live-capture-orchestrator.js')], text=True)
            if not result:
                raise RuntimeError('BROWSER_UNAVAILABLE')
            config['chromium'] = result
    else:
        directory = private_dir(config_path.parent / (config_path.stem + '.runtime'))
    with locked(directory / 'lock'):
        if managed_mode:
            result = managed(args.action, config, directory)
        elif args.action == 'stop':
            stop_owned(directory)
            print('STOPPED (owned server only)')
            return
        elif args.action == 'status' and not owned_alive(runtime_state(directory)):
            print('STOPPED')
            return
        elif args.action == 'rollback':
            raise ValueError('Rollback requires managed capture configuration')
        else:
            result = start_owned(directory, config, config_path) if args.action == 'start' else diagnostic(runtime_state(directory))
        print(json.dumps(result))
        if result.get('url'):
            port = config['web']['port'] if managed_mode else config['port']
            target = args.ssh_target or config.get('web', {}).get('sshTarget', 'USER@LINUX_F')
            print(f'ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:{port}:127.0.0.1:{port} {target}')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
