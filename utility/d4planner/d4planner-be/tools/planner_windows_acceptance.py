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
        started = time.monotonic()
        try: phases[name] = {'status': 'PASS', 'actual': await fn()}
        except Exception as error:
            phases[name] = {'status': 'FAIL', 'error': str(error)}; raise
        finally:
            phases[name]['seconds'] = round(time.monotonic()-started, 3)
            print(name+': '+phases[name]['status'], flush=True)
    try:
        async def hud_startup():
            targets = await wait(lambda: [t for t in json_url(f'http://127.0.0.1:{debug}/json/list')
                if t['type'] == 'page' and 'tauri.localhost' in t['url']], 'owned HUD WebView CDP target')
            return targets[0]
        await phase('installed-hud-startup', hud_startup)
        target = phases['installed-hud-startup']['actual']
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
                # A CDP page exists before the installed WebView has mounted React.
                await wait(lambda: evaluate("!!document.querySelector('.menu-button')"), 'HUD React mounted')
                await evaluate("(()=>{const b=document.querySelector('.menu-button');if(b.getAttribute('aria-expanded')!=='true')b.click();})()")
                await wait(lambda: evaluate("Array.from(document.querySelectorAll('[role=menuitem]')).some(e=>e.textContent==='Create Build'&&!e.disabled)"), 'Create Build enabled')
                await evaluate("Array.from(document.querySelectorAll('[role=menuitem]')).find(e=>e.textContent==='Create Build').click()")
            async def error_contains(text):
                actual = await wait(lambda: evaluate("Array.from(document.querySelectorAll('.hud-error')).map(e=>e.textContent).find(t=>t.startsWith('Local Planner'))"), 'Planner error on HUD')
                assert text in actual, {'expected': text, 'actual': actual}
                return actual
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
        report = {'classification': 'WINDOWS_INSTALLED_VM', 'status': 'PASS' if len(phases) == 8 and all(p['status'] == 'PASS' for p in phases.values()) else 'FAIL',
                  'phases': phases, 'ownerGameFocusController': 'NOT_RUN', 'ci': 'CI_NOT_CHECKED'}
        (output/'report.json').write_text(json.dumps(report, indent=2))
        if report['status'] != 'PASS' and sys.exc_info()[0] is None:
            raise RuntimeError('Installed acceptance failed; see report.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('installation-root', 'data-root', 'provisioned-state', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args))
