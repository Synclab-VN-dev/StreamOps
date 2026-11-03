#!/usr/bin/env python3
"""Private, local acceptance: managed BE -> production Worker -> actual HTTP UI.

Reuse the provider's comprehensive browser/export/visual gates. No online capture,
request interception, calculation selection, or existing service mutation.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[4]
WEB = ROOT / 'utility/d4planner/d4planner-rulekit/providers/maxroll/tooling/web'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


async def run(args):
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    head = git('rev-parse', 'HEAD')
    phases = {}
    proc = None
    stderr = (output/'managed-stderr.log').open('wb')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    identity = {'ownerInstanceId': 'planner-acceptance', 'childInstanceId': 'isolated-backend', 'generation': 1}

    async def phase(name, fn):
        start = time.monotonic()
        try:
            actual = await fn()
            phases[name] = {'status': 'PASS', 'actual': actual}
        except Exception as error:
            phases[name] = {'status': 'FAIL', 'error': str(error)}
            raise
        finally:
            phases[name]['seconds'] = round(time.monotonic()-start, 3)
            print(name + ': ' + phases[name]['status'], flush=True)

    async def command(name, argv):
        with (output/(name+'.log')).open('wb') as log:
            child = await asyncio.create_subprocess_exec(*argv, cwd=WEB, stdout=log, stderr=log)
            try:
                code = await asyncio.wait_for(child.wait(), 600)
            except BaseException:
                if child.returncode is None:
                    child.kill(); await child.wait()
                raise
        assert code == 0, name + ' failed; see private log'
        return {'log': name+'.log'}

    async def read():
        line = await asyncio.wait_for(proc.stdout.readline(), 25)
        assert line, 'Managed process exited before correlated response'
        return json.loads(line)

    async def control(method, request_id):
        message = {'protocolVersion': 'd4planner-control/v1', 'type': 'request', 'requestId': request_id,
                   **identity, 'method': method, 'params': {}}
        proc.stdin.write((json.dumps(message)+'\n').encode()); await proc.stdin.drain()
        response = await read()
        assert response['requestId'] == request_id and response['error'] is None, response
        return response['result']

    try:
        async def preflight():
            assert not git('status', '--porcelain'), 'Commit source before final acceptance'
            # Check the visual dependency before spending minutes in Chromium.
            subprocess.run([sys.executable, '-c', 'from PIL import Image, ImageChops'], check=True)
            state = json.loads((args.state_root/'capture-state.json').read_text())['payload']
            selected = state['packages'][state['activeUi']]
            config = selected['config']
            receipt = json.loads((Path(config['snapshotRoot'])/config['snapshotId']/'ui-validation.json').read_text())
            reference = (args.reference/'report.json').read_bytes()
            assert hashlib.sha256(reference).hexdigest() == receipt['referenceReportSha256']
            reference = json.loads(reference)
            assert reference['status'] == 'PASS' and reference['mode'] == 'ONLINE_REFERENCE'
            assert reference['manifestSha256'] == config['manifestSha256']
            for file, digest in reference['artifactHashes'].items():
                assert Path(file).name == file
                assert hashlib.sha256((args.reference/file).read_bytes()).hexdigest() == digest
            return config
        await phase('reference-and-clean-head', preflight)
        config = phases['reference-and-clean-head']['actual']
        with tempfile.TemporaryDirectory(prefix='planner-acceptance-') as temp:
            data = Path(temp)
            bootstrap = {'protocol': 'd4planner-managed/v1', 'contractVersion': 'd4planner-r1-contract/1.0.0-candidate.6',
                         **identity, 'dataDir': str(data/'data'), 'targetFolder': str(data/'targets'),
                         'wsEndpoint': {'host': '127.0.0.1', 'port': 0}, 'credential': os.urandom(32).hex()}
            file = data/'bootstrap.json'; file.write_text(json.dumps(bootstrap))
            env = {**os.environ, 'PYTHONPATH': str(ROOT/'utility/d4planner/d4planner-be/src'),
                   'D4PLANNER_BOOTSTRAP_FILE': str(file), 'D4PLANNER_RUNTIME_FACTORY': 'd4planner.production:create_runtime',
                   'D4PLANNER_REPOSITORY_ROOT': str(ROOT), 'D4PLANNER_RULEKIT_EXECUTABLE': shutil.which('node'),
                   'D4PLANNER_RULEKIT_WORKING_DIR': str(data), 'D4_RULEKIT_INSTALLATION_ROOT': str(ROOT),
                   'D4_RULEKIT_DATA_ROOT': str(data/'rulekit'), 'D4_RULEKIT_CHROMIUM_EXECUTABLE': str(args.chromium),
                   'D4_RULEKIT_PLANNER_STATE_ROOT': str(args.state_root.resolve()), 'D4_RULEKIT_PLANNER_PORT': str(port)}
            proc = await asyncio.create_subprocess_exec(sys.executable, '-m', 'd4planner.managed_backend', env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr)
            async def startup():
                ready = await read(); assert ready['event'] == 'READY'
                result = await control('planner.ensureReady', 'start')
                assert not result['reused'] and result['status'] == 'READY'
                assert result['snapshotId'] == config['snapshotId'] and result['manifestSha256'] == config['manifestSha256']
                assert result['url'] == f'http://127.0.0.1:{port}/'
                return {'managedPid': proc.pid, 'ready': result, 'backendHealth': ready['health']}
            await phase('production-startup', startup)
            browser = {**config, 'chromium': str(args.chromium), 'online': False,
                       'url': f'http://127.0.0.1:{port}/', 'output': str(output/'http'), 'evidenceDir': str(output/'export')}
            browser_file = output/'browser-config.json'; browser_file.write_text(json.dumps(browser))
            await phase('http-ui', lambda: command('http-ui', ['node', 'full-ui-check.js', str(browser_file)]))
            await phase('native-download-roundtrip', lambda: command('native-download-roundtrip', ['node', 'export-check.js', str(browser_file)]))
            await phase('same-version-visual', lambda: command('same-version-visual', [sys.executable, 'full-visual-check.py', str(args.reference), str(output/'http')]))
            async def reuse():
                result = await control('planner.ensureReady', 'reuse')
                assert result['reused'] and result['snapshotId'] == config['snapshotId']
                await control('target.list', 'targets')
                return {'reused': True, 'managedPid': proc.pid, 'targetList': 'PASS'}
            await phase('reuse-and-target', reuse)
            async def shutdown():
                proc.stdin.write((json.dumps({'type': 'shutdown', **identity})+'\n').encode())
                assert (await read())['event'] == 'EXIT'
                assert await asyncio.wait_for(proc.wait(), 15) == 0
                with socket.socket() as sock:
                    assert sock.connect_ex(('127.0.0.1', port)) != 0, 'Owned listener remains reachable'
                with socket.socket() as sock:
                    # Match Node's SO_REUSEADDR server semantics: TCP TIME_WAIT
                    # connections are not listening processes or leaked ports.
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(('127.0.0.1', port))
                    sock.listen()
                return {'portReleased': port, 'exitCode': 0}
            await phase('shutdown', shutdown)
    finally:
        if proc and proc.returncode is None:
            proc.stdin.close()
            try: await asyncio.wait_for(proc.wait(), 20)
            except asyncio.TimeoutError:
                proc.kill(); await proc.wait()
        stderr.close()
        phases['final-head'] = {'status': 'PASS' if git('rev-parse', 'HEAD') == head and not git('status', '--porcelain') else 'FAIL'}
        status = 'AUTOMATED_PASS' if len(phases) == 8 and all(p['status'] == 'PASS' for p in phases.values()) else 'FAIL'
        report = {'head': head, 'status': status, 'ci': 'CI_NOT_CHECKED', 'windowsInstalled': 'NOT_RUN', 'phases': phases}
        (output/'report.json').write_text(json.dumps(report, indent=2))
        (output/'report.md').write_text(f'# Managed Planner acceptance\n\nHEAD {head}\n\n{status}; CI_NOT_CHECKED\n\n'+
            '\n'.join(f'- {name}: {value["status"]}' for name, value in phases.items())+'\n')
        if status != 'AUTOMATED_PASS' and sys.exc_info()[0] is None:
            raise RuntimeError('Acceptance failed; see report.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('state-root', 'reference', 'chromium', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
