"""Mocked server-side contract tests; no real GitHub writes or cleanup."""
CI_SPEC = {'version': 1, 'id': 'report-gateway',
           'watch': ['.github/workflows/ci.py', '.github/workflows/schedule.yml'],
           'jobs': [{'id': 'mocked-contract', 'profile': 'linux', 'timeout': 300}]}

def run(ctx):
    ctx.python('-m','unittest','discover','-s','utility/d4planner/d4planner-be/report-gateway/tests','-v')
