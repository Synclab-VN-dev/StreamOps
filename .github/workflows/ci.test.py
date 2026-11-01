"""Static wrapper/planner/security tests; component commands live in their contracts."""
CI_SPEC = {'version': 1, 'id': 'ci-engine',
           'watch': ['**/ci.test.py', '**/ci.release.py', 'scripts/ci/**'],
           'ignore': ['docs/**', '*.md', '.gitignore', '.gitattributes', '.github/ISSUE_TEMPLATE/**', '.github/pull_request_template.md'],
           'jobs': [{'id': 'unit', 'profile': 'linux', 'timeout': 300}]}

def run(ctx):
    ctx.python('-m','unittest','discover','-s','.github/workflows/tests','-v')
