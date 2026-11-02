"""Gateway-owned maintenance orchestration; cleanup.py alone decides eligibility."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

CI_SPEC = {'version':1, 'id':'report-gateway-maintenance',
           'jobs':[{'id':'cleanup','operation':'schedule','capability':'maintenance',
                    'profile':'linux','timeout':600}]}


def validate_context(ctx):
    event=ctx.maintenance_event
    if event=='local':
        if not ctx.dry_run:raise ValueError('LOCAL_EXECUTION_NOT_AUTHORIZED')
    else:
        if event not in {'schedule','workflow_dispatch'} or ctx.env.get('GITHUB_EVENT_NAME')!=event:
            raise ValueError('UNTRUSTED_MAINTENANCE_EVENT')
        payload=json.loads(Path(ctx.env['GITHUB_EVENT_PATH']).read_text())
        default=payload['repository']['default_branch']
        if ctx.env.get('GITHUB_REF')!='refs/heads/'+default:
            raise ValueError('TRUSTED_DEFAULT_BRANCH_REQUIRED')
        intended=False if event=='schedule' else payload.get('inputs',{}).get('dry_run','true')
        if event=='workflow_dispatch':
            if type(intended) not in (str,bool) or intended not in ('true','false',True,False):raise ValueError('INVALID_DRY_RUN')
            intended=intended in ('true',True)
        if ctx.dry_run!=intended:raise ValueError('MAINTENANCE_INTENT_MISMATCH')


def load_cleanup(folder):
    sys.path.insert(0,str(folder))
    try:
        spec=importlib.util.spec_from_file_location('gateway_maintenance_domain',folder/'cleanup.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module
    finally:sys.path.pop(0)


def run(ctx, *, domain=None, preflight=None):
    folder=Path(__file__).resolve().parent
    report={'schemaVersion':1,'operation':'issue-log-cleanup','status':'BLOCKED',
            'source':ctx.source['head'],'mode':'dry-run' if ctx.dry_run else 'execute'}
    try:
        validate_context(ctx)
        # Only business tests are preflight: including this orchestration suite
        # would recursively invoke its generic-engine integration test.
        token=ctx.env.pop('GITHUB_TOKEN',None)
        try:
            if preflight is None:
                ctx.python('-m','unittest','discover','-s',folder/'tests','-p','test_reports.py','-v')
            else:preflight()
        finally:
            if token:ctx.env['GITHUB_TOKEN']=token
        release_id=int(ctx.env['DIAGNOSTIC_RELEASE_ID']);bot_id=int(ctx.env['DIAGNOSTIC_BOT_ID'])
        if release_id<=0 or bot_id<=0 or not token:raise ValueError('CONFIGURATION_REQUIRED')
        domain=domain or load_cleanup(folder)
        audit=domain.cleanup(domain.GitHub(lambda:token),release_id,bot_id,
                             datetime.now(timezone.utc),dry_run=ctx.dry_run)
        report.update(status='PASS',counts={
            'wouldDelete':sum(x['action']=='WOULD_DELETE' for x in audit),
            'deleted':sum(x['action']=='DELETED' for x in audit)})
    except Exception:
        # Never expose API error bodies, credentials or private issue content.
        report['reason']='CONTEXT_PREFLIGHT_OR_GITHUB_FAILURE'
        raise RuntimeError(report['reason']) from None
    finally:
        output=ctx.temp/'maintenance.json'
        output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        ctx.artifact(output,'maintenance.json')
