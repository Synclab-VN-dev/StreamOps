#!/usr/bin/env python3
"""Opt-in authorized real capture/activation acceptance on an isolated service. Never CI."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from capture_state import State

WEB = Path(__file__).resolve().parent
PROVIDER = WEB.parent.parent
ROOT = PROVIDER.parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    output = args.output.resolve(); output.mkdir(mode=0o700)
    db = State(config['stateRoot'])
    assert not db.read()['packages'], 'Use a fresh isolated stateRoot; never the Owner service'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', config['web']['port']))
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROVIDER, text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=PROVIDER, text=True).strip()
    original_config = args.config.read_bytes()
    env = {**os.environ, 'MAXROLL_CAPTURE_CONFIG': str(args.config.resolve()),
           'CHROMIUM_EXECUTABLE': config['chromium'], 'BROWSER_INFRA_CHROMIUM_PATH': config['chromium']}
    phases = {}; runtime = None

    def command(name, argv, cwd=PROVIDER, timeout=1500):
        started = time.monotonic()
        with (output / (name + '.log')).open('w') as log:
            result = subprocess.run(argv, cwd=cwd, env=env, stdout=log, stderr=log, timeout=timeout)
        phases[name] = {'status': 'PASS' if result.returncode == 0 else 'FAIL', 'command': list(map(str, argv)), 'duration': time.monotonic()-started, 'evidence': name+'.log'}
        assert result.returncode == 0, name + ' failed; see log'
        return (output / (name + '.log')).read_text()

    def service(name, action):
        text = command(name, ['python3', str(WEB / 'cli.py'), action])
        return json.loads(next(line for line in text.splitlines() if line.startswith('{')))

    def opened(name, runtime):
        active = db.read()['packages'][runtime['snapshotId']]
        cfg = {**active['config'], 'chromium': config['chromium'], 'url': runtime['url'], 'evidenceDir': str(output/name)}
        file = output/(name+'-config.json'); file.write_text(json.dumps(cfg))
        command(name, ['node', str(WEB/'export-check.js'), str(file)])

    try:
        command('cli-orchestration', ['node', '--test', 'tests/unit/snapshot-capture.test.js', 'tests/unit/capture-workflow.test.js'])
        command('registry-activation-negative', ['python3', str(WEB/'capture-state.test.py')])
        command('legacy-calculation', ['npm', 'run', 'snapshot:capture', '--', '--output', str(output/'legacy-calculation')])
        legacy = json.loads((output/'legacy-calculation/capture-report.json').read_text())
        assert legacy['status'] == 'CAPTURED_UNVALIDATED' and legacy['integrity']['status'] == 'PASS'
        command('automatic-calculation', ['npm', 'run', 'snapshot:capture', '--', '--mode', 'calculation'])
        assert not db.read()['activeUi']
        command('capture-ui', ['npm', 'run', 'snapshot:capture', '--', '--mode', 'ui'])
        runtime = service('first-start', 'start'); first_id = runtime['snapshotId']; first_pid = runtime['pid']
        assert service('idempotent-start', 'start')['pid'] == first_pid
        opened('open-first-ui', runtime)
        assert args.config.read_bytes() == original_config
        # Real incomplete capture, cancelled through its normal SIGINT handler. Same CLI/settings.
        before = set(db.read()['runs'])
        with (output/'interrupted-capture.log').open('w') as log:
            proc = subprocess.Popen(['npm', 'run', 'snapshot:capture', '--', '--mode', 'ui'], cwd=PROVIDER, env=env, stdout=log, stderr=log)
            try:
                for _ in range(200):
                    new = set(db.read()['runs']) - before
                    if new: break
                    if proc.poll() is not None: raise RuntimeError('Capture ended before cancellation')
                    time.sleep(.05)
                else: raise RuntimeError('Capture run was not registered')
                run_id = new.pop(); time.sleep(5)
                os.kill(db.read()['runs'][run_id]['ownerPid'], signal.SIGINT)
                assert proc.wait(timeout=90) != 0
                assert db.read()['runs'][run_id]['status'] == 'FAILED'
            finally:
                if proc.poll() is None: proc.terminate(); proc.wait(timeout=10)
        phases['interrupted-capture'] = {'status': 'PASS', 'actual': 'Real npm capture rejected after SIGINT; no candidate promoted', 'evidence': 'interrupted-capture.log'}
        runtime = service('start-after-failed-capture', 'start')
        assert runtime['snapshotId'] == first_id and runtime['pid'] == first_pid
        opened('open-after-failed-capture', runtime)
        command('capture-all', ['npm', 'run', 'snapshot:capture', '--', '--mode', 'all'])
        runs = db.read()['runs']; coordinated = [r for r in runs.values() if r['mode'] == 'all'][-1]
        assert coordinated['status'] == 'COMPLETE' and coordinated['consistency'] == 'PASS'
        packages = [db.read()['packages'][key] for key in coordinated['snapshotIds']]
        assert len(packages) == 2 and {p['kind'] for p in packages} == {'ui', 'calculation'}
        assert next(p for p in packages if p['kind']=='calculation')['validationStatus'] == 'CAPTURED_UNVALIDATED'
        runtime = service('safe-update', 'start'); latest_id = runtime['snapshotId']
        assert latest_id != first_id and runtime['pid'] != first_pid
        opened('open-updated-ui', runtime)
        assert service('rollback', 'rollback')['snapshotId'] == first_id
        assert service('start-after-rollback', 'start')['snapshotId'] == first_id
        assert service('restore-latest', 'rollback')['snapshotId'] == latest_id
        for component in ['application', 'providers/maxroll', 'browser-infra', 'snapshot-management']:
            command(component.replace('/', '-'), ['npm', 'test'], cwd=ROOT/component)
        regression = config['calculationRegression']
        real_env = {'MAXROLL_AUTHORIZED_SNAPSHOT_ROOT':regression['snapshotRoot'], 'MAXROLL_AUTHORIZED_SNAPSHOT_ID':regression['snapshotId'],
                    'MAXROLL_AUTHORIZED_MANIFEST_SHA256':regression['manifestSha256'], 'MAXROLL_SNAPSHOT_AUTHORIZATION_REF':regression['authorizationRef'],
                    'MAXROLL_SOURCE_URL':regression['sourceUrl'], 'MAXROLL_REAL_PROFILE_ID':regression['profileId']}
        env.update(real_env); command('calculation-real', ['npm','run','test:real'])
    finally:
        try:
            service('cleanup', 'stop')
            with socket.socket() as sock: sock.bind(('127.0.0.1', config['web']['port']))
            assert original_config == args.config.read_bytes()
            assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROVIDER,text=True).strip() == head
            assert not subprocess.check_output(['git','status','--porcelain'],cwd=PROVIDER,text=True).strip()
            phases['unchanged-config-head'] = {'status':'PASS','configSha256':hashlib.sha256(original_config).hexdigest(),'head':head}
        except Exception as error:
            phases['cleanup'] = {'status':'FAIL','error':str(error)}
        required=['cli-orchestration','registry-activation-negative','legacy-calculation','automatic-calculation','capture-ui','first-start','idempotent-start','open-first-ui','interrupted-capture','start-after-failed-capture','open-after-failed-capture','capture-all','safe-update','open-updated-ui','rollback','restore-latest','application','providers-maxroll','browser-infra','snapshot-management','calculation-real','cleanup','unchanged-config-head']
        passed=all(phases.get(k,{}).get('status')=='PASS' for k in required)
        definitions=[('CAP-01','CLI backward compatibility',['cli-orchestration','legacy-calculation']),('CAP-02','Comprehensive UI capture and validation',['capture-ui']),('CAP-03','Calculation capture remains unvalidated',['legacy-calculation','automatic-calculation']),('CAP-04','Coordinated identities and drift rejection',['capture-all','cli-orchestration']),('CAP-05','Automatic IDs and pins',['capture-ui','automatic-calculation']),('CAP-06','Concurrent/corrupt metadata',['registry-activation-negative']),('CAP-07','First automatic selection',['first-start']),('CAP-08','Idempotent start',['idempotent-start']),('CAP-09','Validated update',['safe-update','open-updated-ui']),('CAP-10','Rollback and interrupted promotion',['registry-activation-negative','rollback','restore-latest']),('CAP-11','Failed capture leaves active unchanged',['interrupted-capture','start-after-failed-capture','open-after-failed-capture']),('CAP-12','UI/native regression',['capture-ui','capture-all']),('CAP-13','Existing calculation regression',['application','providers-maxroll','browser-infra','snapshot-management','calculation-real']),('CAP-14','Offline/security/ownership/cleanup',['capture-ui','registry-activation-negative','cleanup']),('CAP-15','Unchanged-config three-step workflow across updates',['capture-ui','first-start','open-first-ui','interrupted-capture','start-after-failed-capture','open-after-failed-capture','capture-all','safe-update','open-updated-ui','unchanged-config-head'])]
        ledger=[{'id':i,'expected':expected,'status':'PASS' if all(phases.get(k,{}).get('status')=='PASS' for k in deps) else 'FAIL','actual':{k:phases.get(k,{'status':'NOT_RUN'}) for k in deps},'owner':'F AUTO'} for i,expected,deps in definitions]
        ledger.append({'id':'CAP-16','expected':'Physical Android browser/touch/download after automation','status':'NOT_RUN','owner':'Owner MAN','priorAcceptance':'Owner accepted prior UI before this task'})
        report={'schemaVersion':'maxroll-unified-acceptance/v1','head':head,'status':'LOCAL_PASS' if passed else 'FAIL','ci':'CI_NOT_CHECKED','ledger':ledger,'phases':phases,'state':db.read()}
        (output/'acceptance.json').write_text(json.dumps(report,indent=2))
        (output/'acceptance.md').write_text('# Unified capture acceptance\n\n'+head+'\n\n'+report['status']+' / CI_NOT_CHECKED\n\n| ID | Expected | Actual | Owner |\n|---|---|---|---|\n'+'\n'.join(f"| {r['id']} | {r['expected']} | {r['status']} | {r['owner']} |" for r in ledger)+'\n')
        if not passed: raise RuntimeError('Full local acceptance incomplete; see acceptance.json')


if __name__ == '__main__':
    os.umask(0o077)
    main()
