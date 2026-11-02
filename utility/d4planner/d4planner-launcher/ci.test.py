"""Component-owned CI commands migrated from the corresponding native workflows."""
CI_SPEC = {'version': 1,
 'id': 'd4planner-launcher',
 'watch': ['utility/d4planner/d4planner-hud/runtime-logging/**', '.github/workflows/main.yml', '.github/workflows/ci.py'],
 'depends_on': [],
 'jobs': [{'id': 'native', 'profile': 'windows', 'timeout': 2400, 'tools': {'rust': '1.90.0'}}]}

def run(ctx):
    if ctx.job['id'] == 'native':
        ctx.isolated_python()
        # tests.yml / windows: Build and test D4Planner Launcher
        ctx.shell(r'''
cargo test --locked --release
if ($LASTEXITCODE -ne 0) { throw 'Launcher tests failed' }
cargo build --locked --release
if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed' }
if (-not (Test-Path 'target/release/D4Planner.exe' -PathType Leaf)) {
  throw 'Launcher executable missing after build'
}
''', shell='pwsh', cwd='utility/d4planner/d4planner-launcher')
        return
    raise ValueError("UNKNOWN_JOB")
