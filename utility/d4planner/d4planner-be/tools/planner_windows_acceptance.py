#!/usr/bin/env python3
"""Opt-in installed Windows UAT; run only in an authorized isolated Windows VM.

Exercises actual HUD DOM clicks, Tauri, owned BE/Worker, ShellExecute/default
browser and Root Launcher shutdown. CDP is enabled only for this test's WebView.
Private package/state must already be provisioned with absolute Windows paths.
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from websockets.asyncio.client import connect


def powershell(code):
    encoded = base64.b64encode(code.encode('utf-16-le')).decode()
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, text=True, timeout=25, check=True)
    return json.loads(result.stdout.strip() or 'null')


def processes():
    rows = powershell('Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate | ConvertTo-Json -Compress')
    return rows if isinstance(rows, list) else [rows]


def json_url(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]


async def wait(fn, label, timeout=40):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        try:
            value = fn()
            if asyncio.iscoroutine(value): value = await value
            if value: return value
        except (OSError, ValueError, KeyError):
            pass
        await asyncio.sleep(.2)
    raise AssertionError('Timeout: '+label)


async def run_control(args):
    """Installed Windows IPC/HTTP acceptance when no interactive desktop exists.

    The host runs ordinary HTTP browser tests through its private SSH tunnel,
    then writes browser-complete.json. This does not claim native GUI PASS.
    """
    assert sys.platform == 'win32'
    install, data, output = args.installation_root.resolve(), args.data_root.resolve(), args.output.resolve()
    assert 'Mode=uat' in (install/'installer-identity.ini').read_text(encoding='utf-16')
    assert not data.exists() and not output.exists()
    data.mkdir(parents=True); output.mkdir(parents=True)
    payload = install/json.loads((install/'active.json').read_text())['payload']
    port = free_port()
    identity = {'ownerInstanceId': 'isolated-windows-control', 'childInstanceId': 'backend', 'generation': 1}
    descriptor = {'protocol': 'd4planner-managed/v1', 'contractVersion': 'd4planner-r1-contract/1.0.0-candidate.6',
                  **identity, 'dataDir': str(data/'state'), 'targetFolder': str(data/'targets'),
                  'wsEndpoint': {'host': '127.0.0.1', 'port': 0}, 'credential': os.urandom(32).hex()}
    bootstrap = data/'bootstrap.json'; bootstrap.write_text(json.dumps(descriptor))
    state = data/'rulekit/planner/state'; state.mkdir(parents=True)
    registry = state/'capture-state.json'
    env = {**os.environ, 'PYTHONPATH': str(payload/'backend/site-packages'),
           'D4PLANNER_BOOTSTRAP_FILE': str(bootstrap), 'D4PLANNER_RUNTIME_FACTORY': 'd4planner.production:create_runtime',
           'D4PLANNER_REPOSITORY_ROOT': str(payload), 'D4PLANNER_RULEKIT_EXECUTABLE': str(payload/'runtime/node/node.exe'),
           'D4PLANNER_RULEKIT_WORKER': str(payload/'backend/site-packages/d4planner/rulekit/worker.js'),
           'D4PLANNER_RULEKIT_WORKING_DIR': str(data), 'D4_RULEKIT_INSTALLATION_ROOT': str(payload),
           'D4_RULEKIT_DATA_ROOT': str(data/'rulekit'), 'D4_RULEKIT_PLANNER_PORT': str(port),
           'D4_RULEKIT_CHROMIUM_EXECUTABLE': str(payload/'runtime/chromium/chrome-win64/chrome.exe')}
    env.pop('D4_RULEKIT_PLANNER_STATE_ROOT', None)
    phases = {}
    with (output/'managed-stderr.log').open('wb') as stderr:
        proc = await asyncio.create_subprocess_exec(str(payload/'runtime/python/python.exe'), '-m', 'd4planner.managed_backend',
            env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr)
        async def read():
            return json.loads(await asyncio.wait_for(proc.stdout.readline(), 30))
        def send(id):
            proc.stdin.write((json.dumps({'protocolVersion': 'd4planner-control/v1', 'type': 'request',
                'requestId': id, **identity, 'method': 'planner.ensureReady', 'params': {}})+'\n').encode())
        try:
            ready = await read(); assert ready['event'] == 'READY'
            assert ready['health']['ruleKitProcess'] == 'READY' and ready['health']['ruleKitWorker'] == 'UNAVAILABLE'
            send('missing'); assert (await read())['error']['code'] == 'PLANNER_SNAPSHOT_UNAVAILABLE'
            registry.write_text('{"payload":{},"sha256":"bad"}')
            send('untrusted'); assert (await read())['error']['code'] == 'PLANNER_SNAPSHOT_UNTRUSTED'
            registry.write_bytes(args.provisioned_state.read_bytes())
            with socket.socket() as foreign:
                foreign.bind(('127.0.0.1', port)); foreign.listen()
                send('conflict'); assert (await read())['error']['code'] == 'PLANNER_PORT_CONFLICT'
                assert foreign.getsockname()[1] == port
            phases['negative'] = {'status': 'PASS', 'codes': ['PLANNER_SNAPSHOT_UNAVAILABLE', 'PLANNER_SNAPSHOT_UNTRUSTED', 'PLANNER_PORT_CONFLICT']}
            for i in range(8): send(str(i))
            replies = [await read() for _ in range(8)]
            assert {r['requestId'] for r in replies} == {str(i) for i in range(8)}
            assert all(r['error'] is None and r['result']['status'] == 'READY' for r in replies)
            result = replies[0]['result']
            owner = powershell(f'Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object OwningProcess,LocalAddress | ConvertTo-Json -Compress')
            worker = next(p for p in processes() if p['ProcessId'] == owner['OwningProcess'])
            assert worker['ParentProcessId'] == proc.pid and worker['Name'].lower() == 'node.exe' and owner['LocalAddress'] == '127.0.0.1'
            phases['start-single-flight'] = {'status': 'PASS', 'workerPid': worker['ProcessId'], 'backendPid': proc.pid, 'ready': result}
            (output/'control-ready.json').write_text(json.dumps(result))
            await wait(lambda: (output/'browser-complete.json').exists(), 'host HTTP browser acceptance', timeout=300)
            browser = json.loads((output/'browser-complete.json').read_text())
            assert browser['status'] == 'PASS'; phases['http-browser'] = browser
            send('reuse'); assert (await read())['result']['reused']
            owner_after = powershell(f'Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object OwningProcess | ConvertTo-Json -Compress')
            assert owner_after['OwningProcess'] == worker['ProcessId']
            phases['reuse'] = {'status': 'PASS', 'workerPid': worker['ProcessId']}
            proc.stdin.write((json.dumps({'type': 'shutdown', **identity})+'\n').encode())
            assert (await read())['event'] == 'EXIT'
            assert await asyncio.wait_for(proc.wait(), 20) == 0
            with socket.socket() as sock:
                assert sock.connect_ex(('127.0.0.1', port)) != 0
            phases['shutdown'] = {'status': 'PASS', 'portReleased': port, 'exitCode': 0}
        finally:
            if proc.returncode is None:
                proc.stdin.close()
                try: await asyncio.wait_for(proc.wait(), 20)
                except asyncio.TimeoutError:
                    proc.kill(); await proc.wait()
            report = {'classification': 'WINDOWS_INSTALLED_CONTROL_HTTP', 'status': 'PASS' if len(phases) == 5 else 'FAIL',
                      'phases': phases, 'nativeGuiBrowserOpen': 'NOT_RUN', 'ci': 'CI_NOT_CHECKED'}
            (output/'report.json').write_text(json.dumps(report, indent=2))


async def run(args):
    assert sys.platform == 'win32', 'Requires actual Windows'
    install, data, output = args.installation_root.resolve(), args.data_root.resolve(), args.output.resolve()
    identity = (install/'installer-identity.ini').read_text(encoding='utf-16')
    assert 'Mode=uat' in identity, 'Only isolated UAT installations'
    assert not data.exists() and not output.exists(), 'Use fresh private test directories'
    assert data != install and install not in data.parents
    data.mkdir(parents=True); output.mkdir(parents=True)
    before = processes()
    assert not any(p['Name'].lower() == 'msedge.exe' for p in before), 'Do not reuse another browser session'
    port, debug = free_port(), free_port()
    assert port != debug
    url = f'http://127.0.0.1:{port}/'
    state = data/'rulekit/planner/state'; state.mkdir(parents=True)
    state_file = state/'capture-state.json'
    provisioned = args.provisioned_state.read_bytes()
    selected = json.loads(provisioned)['payload']['activeUi']
    env = {**os.environ, 'D4PLANNER_DATA_ROOT': str(data), 'D4_RULEKIT_PLANNER_PORT': str(port),
           'D4PLANNER_LAUNCH_REPORT': str(output/'launcher.json'),
           'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS': f'--remote-debugging-port={debug} --force-renderer-accessibility'}
    env.pop('D4_RULEKIT_PLANNER_STATE_ROOT', None)
    launcher = subprocess.Popen([str(install/'D4Planner.exe')], cwd=output, env=env)
    phases, owned_browser = {}, []
    async def phase(name, fn):
        try: phases[name] = {'status': 'PASS', 'actual': await fn()}
        except Exception as error:
            phases[name] = {'status': 'FAIL', 'error': str(error)}; raise
        finally: print(name+': '+phases[name]['status'], flush=True)
    try:
        targets = await wait(lambda: json_url(f'http://127.0.0.1:{debug}/json/list'), 'owned WebView CDP')
        target = next(t for t in targets if t['type'] == 'page' and 'tauri.localhost' in t['url'])
        async with connect(target['webSocketDebuggerUrl'], proxy=None) as ws:
            seq = 0
            async def cdp(method, params=None):
                nonlocal seq
                seq += 1; current = seq
                await ws.send(json.dumps({'id': current, 'method': method, 'params': params or {}}))
                while True:
                    reply = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    if reply.get('id') == current:
                        assert 'error' not in reply, reply
                        return reply['result']
            async def evaluate(expression):
                result = await cdp('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
                assert 'exceptionDetails' not in result, result
                return result['result'].get('value')
            async def screenshot(name):
                value = await cdp('Page.captureScreenshot')
                (output/(name+'.png')).write_bytes(base64.b64decode(value['data']))
            async def click_create():
                await evaluate("(()=>{const b=document.querySelector('.menu-button');if(b.getAttribute('aria-expanded')!=='true')b.click();})()")
                await wait(lambda: evaluate("Array.from(document.querySelectorAll('[role=menuitem]')).some(e=>e.textContent==='Create Build'&&!e.disabled)"), 'Create Build enabled')
                await evaluate("Array.from(document.querySelectorAll('[role=menuitem]')).find(e=>e.textContent==='Create Build').click()")
            async def error_contains(text):
                return await wait(lambda: evaluate('document.body.innerText.includes('+json.dumps(text)+')'), text)
            async def missing():
                await click_create(); await error_contains('snapshot is unavailable')
                await screenshot('missing-snapshot')
                assert not any(p['Name'].lower() == 'msedge.exe' for p in processes())
                return {'browserOpened': False}
            await phase('missing-snapshot-hud', missing)
            async def untrusted():
                state_file.write_text('{"payload":{},"sha256":"bad"}')
                await click_create(); await error_contains('could not be verified')
                assert not any(p['Name'].lower() == 'msedge.exe' for p in processes())
                return {'browserOpened': False}
            await phase('untrusted-snapshot-hud', untrusted)
            state_file.write_bytes(provisioned)
            async def conflict():
                with socket.socket() as foreign:
                    foreign.bind(('127.0.0.1', port)); foreign.listen()
                    await click_create(); await error_contains('port is in use')
                    assert foreign.getsockname()[1] == port
                    assert not any(p['Name'].lower() == 'msedge.exe' for p in processes())
                return {'foreignListenerPreserved': True, 'browserOpened': False}
            await phase('foreign-port-hud', conflict)
            async def startup():
                await click_create()
                diagnostics = await wait(lambda: json_url(url+'__local/diagnostics'), 'owned Planner HTTP')
                assert diagnostics['snapshotId'] == selected
                nonlocal owned_browser
                owned_browser = await wait(lambda: [p for p in processes() if p['Name'].lower() == 'msedge.exe' and url in (p['CommandLine'] or '')], 'default system browser with exact URL')
                diagnostics = await wait(lambda: (lambda d: d if d['served'] > 50 and any(
                    event['kind'] == 'FRAME_STATE' and event.get('detail', {}).get('newProfile') is True
                    for event in d['clientEvents']) else None)(json_url(url+'__local/diagnostics')),
                    'actual system browser rendered native New Profile')
                assert not any(event['kind'] in {'JS_ERROR', 'UNHANDLED_REJECTION'} for event in diagnostics['clientEvents'])
                rows = processes()
                node = [p for p in rows if p['Name'].lower() == 'node.exe' and str(install).lower() in (p['CommandLine'] or '').lower()]
                assert len(node) == 1, 'Exactly one installed Rule Kit Worker'
                await screenshot('ready-hud')
                return {'workerPid': node[0]['ProcessId'], 'url': url, 'snapshotId': selected,
                        'manifestSha256': diagnostics['manifestSha256'], 'served': diagnostics['served'],
                        'defaultBrowserPid': owned_browser[0]['ProcessId']}
            await phase('installed-create-build-system-browser', startup)
            async def reuse():
                await click_create()
                await wait(lambda: evaluate("!document.querySelector('.target-menu')"), 'READY closed menu')
                owners = powershell(f'Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object OwningProcess,LocalAddress | ConvertTo-Json -Compress')
                assert owners['OwningProcess'] == phases['installed-create-build-system-browser']['actual']['workerPid']
                assert owners['LocalAddress'] == '127.0.0.1'
                return {'sameWorkerPid': owners['OwningProcess'], 'noSecondServer': True}
            await phase('installed-ready-reuse', reuse)
            async def menu_regression():
                await evaluate("document.querySelector('.menu-button').click()")
                assert await evaluate("document.querySelector('.target-menu').innerText.includes('Target Build')")
                await evaluate("Array.from(document.querySelectorAll('[role=menuitem]')).find(e=>e.textContent==='Report Issue').click()")
                await wait(lambda: evaluate("!!document.querySelector('[aria-label=\"Close report\"]')"), 'Report Issue form')
                await evaluate("document.querySelector('[aria-label=\"Close report\"]').click()")
                return {'reportIssueOpenClose': True, 'targetMenuPresent': True}
            await phase('installed-existing-menu', menu_regression)
    finally:
        # Record diagnostics before retiring this test's own process tree. A
        # launch failure must not disappear behind a secondary cleanup error.
        (output/'processes-before-stop.json').write_text(json.dumps(processes(), indent=2))
        try:
            subprocess.run([str(install/'D4Planner.exe'), '--stop'], env=env, timeout=20, check=True)
            launcher.wait(timeout=25)
            with socket.socket() as sock:
                assert sock.connect_ex(('127.0.0.1', port)) != 0, 'Owned HTTP port leaked'
            assert launcher.returncode == 0
            phases['installed-shutdown'] = {'status': 'PASS', 'actual': {'exitCode': launcher.returncode, 'portReleased': port}}
        except Exception as error:
            phases['installed-shutdown'] = {'status': 'FAIL', 'error': str(error)}
            if launcher.poll() is None:
                launcher.kill(); launcher.wait(timeout=10)  # exact Popen handle; never a PID search
        # ShellExecute can delegate outside the launcher Job Object. Retire only
        # exact browser PID/start-time/URL observations created by this test.
        for observed in owned_browser:
            current = next((p for p in processes() if p['ProcessId'] == observed['ProcessId']), None)
            if current and current['CreationDate'] == observed['CreationDate'] and url in (current['CommandLine'] or ''):
                subprocess.run(['taskkill.exe', '/PID', str(current['ProcessId']), '/T', '/F'], check=True, timeout=20)
        report = {'classification': 'WINDOWS_INSTALLED_VM', 'status': 'PASS' if len(phases) == 7 and all(p['status'] == 'PASS' for p in phases.values()) else 'FAIL',
                  'phases': phases, 'ownerGameFocusController': 'NOT_RUN', 'ci': 'CI_NOT_CHECKED'}
        (output/'report.json').write_text(json.dumps(report, indent=2))
        if report['status'] != 'PASS' and sys.exc_info()[0] is None:
            raise RuntimeError('Installed acceptance failed; see report.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('installation-root', 'data-root', 'provisioned-state', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--control-only', action='store_true', help='Installed IPC/HTTP only; never claims native GUI PASS')
    args = parser.parse_args()
    asyncio.run(run_control(args) if args.control_only else run(args))
