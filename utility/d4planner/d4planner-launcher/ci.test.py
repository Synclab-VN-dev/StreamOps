"""Component-owned CI commands migrated from the corresponding native workflows."""
CI_SPEC = {'version': 1,
 'id': 'd4planner-launcher',
 'watch': ['utility/d4planner/d4planner-hud/runtime-logging/**',
           'utility/d4planner/d4planner-be/tools/windows_install.py',
           'utility/d4planner/d4planner-be/tools/installer_*regression.*',
           'utility/d4planner/d4planner-be/tools/storage_native_smoke.py',
           'utility/d4planner/d4planner-be/tools/build_windows_installer.py',
           'utility/d4planner/d4planner-be/release1/installer.nsi',
           'utility/d4planner/d4planner-be/src/d4planner/runtime/storage*',
           'utility/d4planner/d4planner-be/src/d4planner/runtime/migration.py',
           '.github/workflows/main.yml', '.github/workflows/ci.py'],
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
        try:
            ctx.shell(r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Join-Path $pwd 'utility/d4planner/d4planner-be/tools/installer_setup_regression.ps1'),
  [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count) { throw ($errors | Out-String) }
$env:PYTHONPATH = Join-Path $pwd 'utility/d4planner/d4planner-be/src'
$launcher = Join-Path $pwd 'utility/d4planner/d4planner-launcher/target/release/D4Planner.exe'
python utility/d4planner/d4planner-be/tools/installer_native_regression.py `
  --launcher $launcher --sandbox (Join-Path $env:RUNNER_TEMP 'issue184-native')
if ($LASTEXITCODE -ne 0) { throw 'Issue184 Windows dialog regression failed' }
''', shell='pwsh', cwd='.')
        finally:
            report = ctx.temp / 'issue184-native' / 'report.json'
            if report.exists():
                ctx.artifact(report, 'issue184-native.json')
        return
    raise ValueError("UNKNOWN_JOB")
