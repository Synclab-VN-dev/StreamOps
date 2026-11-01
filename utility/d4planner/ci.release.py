"""Product release adapter: VM and Actions reuse BE tools/release_ci.py."""
import json

CI_SPEC = {'version':1,'id':'d4planner-release','release_tags':['d4planner-uat/v*'],
           'depends_on':['d4planner-launcher','d4planner-be','d4planner-hud','d4planner-rulekit'],
           'jobs':[
               {'id':'setup','profile':'windows','timeout':3600,'operation':'build','capability':'public-inputs',
                'tools':{'node':'22.22.1','rust':'1.90.0'},
                'secrets':{'D4_PUBLIC_RUNTIME_INPUT_URL':'D4PLANNER_PUBLIC_RUNTIME_INPUTS_URL',
                           'D4_PUBLIC_RUNTIME_INPUT_SHA256':'D4PLANNER_PUBLIC_RUNTIME_INPUTS_SHA256'}},
               {'id':'publish','profile':'windows','timeout':900,'operation':'publish','capability':'publish'}]}


def run(ctx):
    root=ctx.root/'utility/d4planner/d4planner-be'
    version=ctx.version
    if ctx.channel=='uat':
        version=json.loads((root/'release1/package-plan.json').read_text())['version']
    if not version:raise ValueError('VERSION_REQUIRED')
    core=root/'tools/release_ci.py'
    common=['--channel',ctx.channel,'--version',version,'--source',ctx.source['head']]
    if ctx.job['operation']=='build':
        ctx.isolated_python()
        ctx.tool('node','22.22.1');ctx.tool('rustc','1.90.0')
        ctx.env['RUSTUP_TOOLCHAIN']='1.90.0'
        ctx.python('-m','pip','install','setuptools==80.9.0','wheel==0.45.1','pytest==9.1.1',
                   '-r',root/'release1/requirements-release.txt')
        directory=ctx.temp/'d4-release'
        ctx.env['D4_BUILD_ONLY']='false' if ctx.intent=='publish' else 'true'
        # Build-only never consults Release existence; UAT context is still checked by core build.
        if ctx.intent=='publish' or ctx.channel=='stable':ctx.python(core,'validate',*common,'--directory',directory)
        ctx.shell(r'''
$owned = Join-Path $env:RUNNER_TEMP 'd4-release'
New-Item -ItemType Directory -Force $owned | Out-Null
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $owned /inheritance:r /grant:r "${account}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F'
if ($LASTEXITCODE -ne 0) { throw 'Private build ACL failed' }
''',shell='pwsh')
        ctx.python(core,'build',*common,'--directory',directory)
        outputs=dict(line.split('=',1) for line in open(ctx.env['GITHUB_OUTPUT']) if '=' in line)
        ctx.env['D4_BUILT_SETUP_SHA256']=outputs['setup_sha256'].strip()
        artifact=directory/'build/verified-artifact'
        ctx.python(core,'prepare-upload',*common,'--directory',artifact)
        ctx.python(core,'validate-upload',*common,'--directory',artifact)
        ctx.artifact(artifact,'setup')
    else:
        artifact=ctx.build_artifact('setup')
        metadata=json.loads((artifact/'release-metadata.json').read_text())
        ctx.env['D4_BUILT_SETUP_SHA256']=metadata['sha256']
        ctx.python(core,'publish-uat' if ctx.channel=='uat' else 'publish',*common,'--directory',artifact)
