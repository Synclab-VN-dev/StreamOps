"""Component-owned CI commands migrated from the corresponding native workflows."""
CI_SPEC = {'version': 1,
 'id': 'd4planner-be',
 'watch': ['.github/workflows/main.yml',
           '.github/workflows/ci.py',
           'scripts/e2e/issue87*',
           'scripts/e2e/issue95*',
           'scripts/acceptance/issue87*',
           'scripts/acceptance/issue95*',
           'utility/d4planner/script/build/**'],
 'depends_on': ['d4planner-rulekit', 'd4planner-launcher', 'd4planner-hud'],
 'jobs': [{'id': 'portability', 'profile': 'linux', 'timeout': 480},
          {'id': 'native',
           'profile': 'windows',
           'timeout': 2400,
           'tools': {'node': '22.23.4'}}]}

def run(ctx):
    if ctx.job['id'] == 'portability':
        ctx.isolated_python()
        # tests.yml / d4planner-portability: Install D4Planner package and tests
        ctx.shell(r'''
python -m pip install -e 'utility/d4planner/d4planner-be[dev]'
''', shell='bash', cwd='.')
        # tests.yml / d4planner-portability: Linux pure controller regression (no Steam/Win32)
        ctx.shell(r'''
python -m pytest -q \
  utility/d4planner/d4planner-be/tests/test_controller_contract.py \
  utility/d4planner/d4planner-be/tests/test_controller_additional_gates.py \
  utility/d4planner/d4planner-be/tests/test_multi_key_hook.py \
  utility/d4planner/d4planner-be/tests/test_multi_key_capture.py \
  utility/d4planner/d4planner-be/tests/test_issue87_uat_evidence.py \
  utility/d4planner/script/build/tests
''', shell='bash', cwd='.')
        # tests.yml / d4planner-portability: Controller CLI validate on Linux
        ctx.shell(r'''
python -m d4planner.cli controller profiles
python -m d4planner.cli controller validate xbox16
''', shell='bash', cwd='.')
        return
    if ctx.job['id'] == 'native':
        ctx.isolated_python()
        # tests.yml / windows: Install D4Planner dev dependencies
        ctx.shell(r'''
python -m pip install -e 'utility/d4planner/d4planner-be[dev]'
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Install locked Rule Kit worker dependencies
        ctx.shell(r'''
$ErrorActionPreference = 'Stop'
foreach ($package in @('snapshot-management', 'browser-infra', 'providers/maxroll', 'application')) {
  npm ci --prefix "utility/d4planner/d4planner-rulekit/$package"
  if ($LASTEXITCODE -ne 0) { throw "Rule Kit dependency install failed: $package" }
}
node -e "require('./utility/d4planner/d4planner-rulekit/snapshot-management/src/manager'); require('./utility/d4planner/d4planner-be/tests/fixtures/snapshot-test-composition'); console.log('Rule Kit dependency preflight PASS')"
if ($LASTEXITCODE -ne 0) { throw 'Rule Kit dependency preflight failed before pytest' }
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Test D4Planner runtime
        ctx.shell(r'''
python -m pytest -q utility/d4planner/d4planner-be/tests utility/d4planner/script/build/tests
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Issue87 UT-04 and E2E-03/11 required gates (synthetic CI)
        ctx.shell(r'''
$ErrorActionPreference = 'Stop'
python -m pytest -q utility/d4planner/d4planner-be/tests/test_controller_additional_gates.py -k 'test_ut04_vk_mapping_is_keylayout_independent'
if ($LASTEXITCODE -ne 0) { throw 'Issue87 UT-04 failed' }
python -m pytest -q utility/d4planner/d4planner-be/tests/test_e2e_cli_runtime.py -k 'test_e2e03_xbox16_session1_one_hook_end_to_end_to_sqlite or test_e2e11_stop_unhooks_then_mode_switch_without_stale_capture'
if ($LASTEXITCODE -ne 0) { throw 'Issue87 E2E-03/11 failed' }
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Compile D4Planner runtime
        ctx.shell(r'''
python -m compileall -q utility/d4planner/d4planner-be
''', shell='pwsh', cwd='.')
        # tests.yml / windows: D4Planner V1 packaged wheel smoke (isolated)
        ctx.shell(r'''
$ErrorActionPreference = 'Stop'
$wheelDir = Join-Path $env:RUNNER_TEMP 'd4planner-wheel'
$venvDir = Join-Path $env:RUNNER_TEMP 'd4planner-wheel-venv'
New-Item -ItemType Directory -Force $wheelDir | Out-Null
python -m pip wheel --no-deps --wheel-dir $wheelDir utility/d4planner/d4planner-be
if ($LASTEXITCODE -ne 0) { throw 'D4Planner wheel build failed' }
$wheel = @(Get-ChildItem $wheelDir -Filter 'd4planner-*.whl')
if ($wheel.Count -ne 1) { throw "Expected exactly one D4Planner wheel, got $($wheel.Count)" }
python -m venv $venvDir
if ($LASTEXITCODE -ne 0) { throw 'D4Planner isolated venv creation failed' }
$isolatedPython = Join-Path $venvDir 'Scripts/python.exe'
& $isolatedPython -m pip install --no-index --no-deps $wheel[0].FullName
if ($LASTEXITCODE -ne 0) { throw 'D4Planner isolated wheel install failed' }
Push-Location $env:RUNNER_TEMP
try {
  & $isolatedPython -I -m d4planner.cli controller validate xbox16
  if ($LASTEXITCODE -ne 0) { throw 'D4Planner installed wheel profile validation failed' }
  & $isolatedPython -I -m d4planner.cli controller profiles
  if ($LASTEXITCODE -ne 0) { throw 'D4Planner installed wheel profile discovery failed' }
} finally {
  Pop-Location
}
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Parse issue87 read-only acceptance PowerShell
        ctx.shell(r'''
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path 'scripts/acceptance/issue87-uat.ps1').Path,
  [ref]$tokens, [ref]$errors
) | Out-Null
if ($errors.Count -gt 0) { throw ($errors | Out-String) }
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path 'scripts/acceptance/issue87-real-a-uat.ps1').Path,
  [ref]$tokens, [ref]$errors
) | Out-Null
if ($errors.Count -gt 0) { throw ($errors | Out-String) }
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Issue87 UAT safe preflight smoke (no runtime start)
        ctx.shell(r'''
$ErrorActionPreference = 'Stop'
# Missing hook must return status=BLOCKED (exit=2); inspect that exit
# explicitly rather than treating a nonzero child as a PowerShell crash.
$PSNativeCommandUseErrorActionPreference = $false
$homeDir = Join-Path $env:RUNNER_TEMP 'issue87-empty-home'
$evidence = Join-Path $env:RUNNER_TEMP 'issue87-preflight-smoke'
New-Item -ItemType Directory -Force $homeDir | Out-Null
& pwsh -NoProfile -File ./scripts/acceptance/issue87-uat.ps1 `
  -Mode Preflight -DataDir $homeDir -EvidenceDir $evidence
$preflightExit = $LASTEXITCODE
# GitHub's pwsh runner implicitly exits with LASTEXITCODE at the
# end of a job step; BLOCKED is expected in this negative test.
$global:LASTEXITCODE = 0
if ($preflightExit -ne 2) {
  throw "Expected BLOCKED without a running Session1 hook, got $preflightExit"
}
$report = Get-Content (Join-Path $evidence 'preflight.json') -Raw | ConvertFrom-Json
$byId = @{}
foreach ($item in $report.checks) { $byId[$item.id] = $item.result }
if ($byId['PF-03A'] -ne 'PASS' -or $byId['PF-03B'] -ne 'PASS') {
  throw 'Controller CLI profile/validate failed in UAT preflight smoke'
}
if ($byId['PF-04'] -ne 'BLOCKED') {
  throw 'Unsafe false PASS: missing live hook was not blocked'
}
Write-Host 'Issue87 read-only negative preflight PASS: CLI validated; no live hook was accepted'
$global:LASTEXITCODE = 0
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Issue87 Real-A UAT detached HEAD Preflight regression
        ctx.shell(r'''
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$head = (& git rev-parse HEAD).Trim()
# Owner tests the pinned PR in a detached worktree. Reproduce that
# exact Git state, not just a PowerShell parser/synthetic test.
& git -c advice.detachedHead=false checkout --detach HEAD
if ($LASTEXITCODE -ne 0) { throw 'Unable to enter detached HEAD test state' }
$branch = & git branch --show-current
if ($branch) { throw "Expected detached HEAD, saw branch: $branch" }
$evidence = Join-Path $env:RUNNER_TEMP 'issue87-real-a-detached-preflight'
& pwsh -NoProfile -File ./scripts/acceptance/issue87-real-a-uat.ps1 `
  -Mode Preflight -ExpectedHead $head -EvidenceDir $evidence
$scriptExit = $LASTEXITCODE
$global:LASTEXITCODE = 0
if ($scriptExit -ne 0) {
  if (Test-Path (Join-Path $evidence 'report.json')) {
    Get-Content (Join-Path $evidence 'report.json') -Raw | Write-Host
  }
  throw "Real-A detached HEAD preflight failed: exit=$scriptExit"
}
$report = Get-Content (Join-Path $evidence 'report.json') -Raw | ConvertFrom-Json
if ($report.head -ne $head -or $report.mode -ne 'Preflight') {
  throw 'Preflight did not report the expected detached commit and mode'
}
$byId = @{}
foreach ($item in $report.checks) { $byId[$item.id] = $item.result }
if ($byId['DF-01'] -ne 'PASS' -or $byId['DF-03'] -ne 'PASS') {
  throw 'Detached Preflight failed its read-only Git/context/profile checks'
}
if ($report.taskCreatedByScript -or $report.taskStartedByScript) {
  throw 'Preflight must never create or start an interactive task'
}
Write-Host 'Issue87 detached worktree preflight PASS (no task/runtime created)'
$global:LASTEXITCODE = 0
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Issue87 Real-A locale marshalling regression
        ctx.shell(r'''
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$head = (& git rev-parse HEAD).Trim()
$branch = & git branch --show-current
if ($branch) { throw 'Expected detached HEAD from prior UAT test' }
$env:ISSUE87_EXPECTED_HEAD = $head
$env:ISSUE87_EVIDENCE = Join-Path $env:RUNNER_TEMP 'issue87-winrt-interop-smoke'
# Simulate the PowerShell/Windows A WinRT failure even if the runner's
# OS supports this API. Calling Get-WinUserLanguageList must NOT be
# required for read-only UAT baseline or crash the Preflight.
& pwsh -NoProfile -Command @'
function global:Get-WinUserLanguageList {
  throw "Cannot marshal 'parameter #2': Invalid managed/unmanaged type combination."
}
& ./scripts/acceptance/issue87-real-a-uat.ps1 -Mode Preflight `
  -ExpectedHead $env:ISSUE87_EXPECTED_HEAD -EvidenceDir $env:ISSUE87_EVIDENCE
'@
$smokeExit = $LASTEXITCODE
$global:LASTEXITCODE = 0
if ($smokeExit -ne 0) {
  if (Test-Path (Join-Path $env:ISSUE87_EVIDENCE 'report.json')) {
    Get-Content (Join-Path $env:ISSUE87_EVIDENCE 'report.json') -Raw | Write-Host
  }
  throw "Issue87 simulated locale-marshalling Preflight failed: $smokeExit"
}
$report = Get-Content (Join-Path $env:ISSUE87_EVIDENCE 'report.json') -Raw | ConvertFrom-Json
$df = $report.checks | Where-Object { $_.id -eq 'DF-01' } | Select-Object -First 1
if ($null -eq $df -or $df.result -ne 'PASS' -or
    $null -eq $df.actual.userCulture -or
    $null -eq $df.actual.keyboardLayoutPreload) {
  throw 'Missing read-only culture/keyboard-layout evidence in DF-01'
}
if ($report.taskCreatedByScript -or $report.taskStartedByScript) {
  throw 'Preflight must not start or create any interactive task'
}
Write-Host 'Issue87 WinRT-marshalling simulated failure regression PASS'
$global:LASTEXITCODE = 0
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Issue87 UAT preflight with foreign editable Python installation
        ctx.shell(r'''
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$head = (& git rev-parse HEAD).Trim()
$foreign = Join-Path $env:RUNNER_TEMP 'issue87-old-worktree82/src'
New-Item -ItemType Directory -Force (Join-Path $foreign 'd4planner') | Out-Null
Set-Content (Join-Path $foreign 'd4planner/__init__.py') `
  'raise RuntimeError("IMPORTED_FOREIGN_WORKTREE82")' -Encoding utf8
$prior = $env:PYTHONPATH
$env:PYTHONPATH = $foreign
$evidence = Join-Path $env:RUNNER_TEMP 'issue87-foreign-python-preflight'
try {
  & pwsh -NoProfile -File ./scripts/acceptance/issue87-real-a-uat.ps1 `
    -Mode Preflight -ExpectedHead $head -EvidenceDir $evidence
  $code = $LASTEXITCODE
  $global:LASTEXITCODE = 0
  if ($code -ne 0) {
    Get-Content (Join-Path $evidence 'report.json') -Raw | Write-Host
    throw "Foreign-worktree preflight unexpectedly BLOCKED: exit=$code"
  }
  $report = Get-Content (Join-Path $evidence 'report.json') -Raw | ConvertFrom-Json
  $mapped = @{}
  foreach ($item in $report.checks) { $mapped[$item.id] = $item.result }
  if ($mapped['DF-01'] -ne 'PASS' -or $mapped['DF-03'] -ne 'PASS') {
    throw "Wrong PR95 module or controller contract was used"
  }
  $log = Get-Content (Join-Path $evidence 'module-path.log') -Raw
  if ($log -notlike '*utility*d4planner*src*d4planner*__init__.py*') {
    throw "Module path was not pinned to PR95: $log"
  }
  if ($report.taskCreatedByScript -or $report.taskStartedByScript) {
    throw 'Read-only Preflight must not create any scheduled task'
  }
} finally {
  $env:PYTHONPATH = $prior
  $global:LASTEXITCODE = 0
}
Write-Host 'Issue87 foreign Python source override PASS'
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Issue87 isolated PR95 Python venv local CI smoke
        ctx.shell(r'''
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$head = (& git rev-parse HEAD).Trim()
$evidence = Join-Path $env:RUNNER_TEMP 'issue87-venv-local-ci'
& pwsh -NoProfile -File ./scripts/acceptance/issue87-real-a-uat.ps1 `
  -Mode Preflight -RunLocalCI -ExpectedHead $head -EvidenceDir $evidence
$code = $LASTEXITCODE
$global:LASTEXITCODE = 0
if ($code -ne 0) {
  Get-Content (Join-Path $evidence 'report.json') -Raw | Write-Host
  throw "Isolated PR95 local CI smoke failed: $code"
}
$r = Get-Content (Join-Path $evidence 'report.json') -Raw | ConvertFrom-Json
$byId = @{}
foreach($entry in $r.checks) { $byId[$entry.id] = $entry.result }
if ($byId['DF-02'] -ne 'PASS' -or $byId['DF-03'] -ne 'PASS') {
  throw 'Isolated local pytest/compile/profile acceptance incomplete'
}
$venv = Join-Path $pwd '.streamops/pr95/python-venv/Scripts/python.exe'
if (!(Test-Path $venv)) { throw 'PR95 virtualenv python missing' }
& $venv -I -c 'import d4planner;print(d4planner.__file__)'
if ($LASTEXITCODE -ne 0) { throw 'PR95 source unavailable with isolated Python -I' }
if ($r.taskCreatedByScript -or $r.taskStartedByScript) {
  throw 'Preflight -RunLocalCI must not create a scheduled task'
}
Write-Host 'Issue87 isolated venv local CI smoke PASS'
$global:LASTEXITCODE = 0
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Build D4Planner NVDA add-on
        ctx.shell(r'''
python utility/d4planner/d4planner-be/tools/build_nvda_addon.py
''', shell='pwsh', cwd='.')
        for addon in (ctx.root/'utility/d4planner/d4planner-be/dist').glob('*.nvda-addon'):
            ctx.artifact(addon)
        return
    raise ValueError("UNKNOWN_JOB")
