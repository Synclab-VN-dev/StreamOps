"""VM wrapper unit/PowerShell syntax checks. Never starts a VM."""
CI_SPEC = {'version': 1, 'id': 'd4planner-build-tools',
           'watch': ['.github/workflows/ci.py', '.github/workflows/main.yml'],
           'jobs': [{'id': 'unit', 'profile': 'linux', 'timeout': 300}]}

def run(ctx):
    ctx.isolated_python()
    ctx.python('-m','pip','install','pytest==9.1.1')
    ctx.python('-m','pytest','-q','utility/d4planner/script/build/tests')
