#!/usr/bin/env python3
"""Maintenance orchestration; deletion eligibility remains owned by Report Gateway."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
GATEWAY = ROOT / 'utility/d4planner/d4planner-be/report-gateway'


def mode(event, dry_run):
    if event not in ('schedule', 'workflow_dispatch', 'local'):
        raise ValueError('UNTRUSTED_MAINTENANCE_EVENT')
    if event == 'local' and not dry_run:
        raise ValueError('LOCAL_EXECUTION_NOT_AUTHORIZED')
    return event != 'schedule' and dry_run


def load_cleanup():
    sys.path.insert(0, str(GATEWAY))
    try:
        spec = importlib.util.spec_from_file_location('maintenance_domain', GATEWAY / 'cleanup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def run(event, dry_run, output, *, domain=None, env=None, preflight=None):
    env = os.environ if env is None else env
    started = time.monotonic()
    report = {'schemaVersion': 1, 'operation': 'issue-log-cleanup', 'status': 'BLOCKED',
              'source': subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
              'startedAt': datetime.now(timezone.utc).isoformat(), 'exitCode': 1}
    try:
        dry_run = mode(event, dry_run)
        report['mode'] = 'dry-run' if dry_run else 'execute'
        if event != 'local':
            if env.get('GITHUB_EVENT_NAME') != event:
                raise ValueError('EVENT_CONTEXT_MISMATCH')
            default = json.loads(Path(env['GITHUB_EVENT_PATH']).read_text())['repository']['default_branch']
            if env.get('GITHUB_REF') != 'refs/heads/' + default:
                raise ValueError('TRUSTED_DEFAULT_BRANCH_REQUIRED')
        if preflight is None:
            subprocess.run([sys.executable,'-m','unittest','discover','-s',str(GATEWAY/'tests'),'-v'],
                           check=True, timeout=180, env={k:v for k,v in env.items() if k != 'GITHUB_TOKEN'})
        else:
            preflight()
        release_id, bot_id = int(env['DIAGNOSTIC_RELEASE_ID']), int(env['DIAGNOSTIC_BOT_ID'])
        if release_id <= 0 or bot_id <= 0 or not env.get('GITHUB_TOKEN'):
            raise ValueError('CONFIGURATION_REQUIRED')
        domain = domain or load_cleanup()
        github = domain.GitHub(lambda: env['GITHUB_TOKEN'])
        audit = domain.cleanup(github,release_id,bot_id,datetime.now(timezone.utc),dry_run=dry_run)
        # Public counts only; no credentials, issue content or private diagnostics.
        report.update(status='PASS',exitCode=0,counts={
            'wouldDelete':sum(x['action']=='WOULD_DELETE' for x in audit),
            'deleted':sum(x['action']=='DELETED' for x in audit)})
    except Exception:
        report['reason'] = 'CONTEXT_PREFLIGHT_OR_GITHUB_FAILURE'
    report['seconds'] = round(time.monotonic()-started,3)
    report['finishedAt'] = datetime.now(timezone.utc).isoformat()
    output = Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    return report['exitCode']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event',default='local',choices=['local','schedule','workflow_dispatch'])
    parser.add_argument('--dry-run',choices=['true','false'],default='true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    return run(args.event,args.dry_run=='true',args.output)

if __name__=='__main__':raise SystemExit(main())
