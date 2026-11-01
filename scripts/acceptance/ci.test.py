"""Read-only UAT harness selftest and expected-BLOCKED negative smoke; no Host A actions."""
CI_SPEC = {'id': 'operator-acceptance',
 'jobs': [{'id': 'read-only-harness', 'profile': 'windows', 'timeout': 300}],
 'version': 1,
 'watch': []}

def run(ctx):
    ctx.shell(r'''
$root = Join-Path $env:RUNNER_TEMP 'issue86-uat-runner'
& pwsh -NoProfile -File ./scripts/acceptance/issue86-pr89-uat.ps1 -Mode SelfTest -OutputRoot $root
if ($LASTEXITCODE -ne 0) { throw 'Issue86 runner SelfTest failed' }
$selftest = Get-ChildItem -LiteralPath $root -Recurse -Filter report.json |
  Where-Object { (Get-Content $_.FullName -Raw | ConvertFrom-Json).metadata.mode -eq 'SelfTest' } |
  Select-Object -First 1
if (-not $selftest) { throw 'Missing UAT SelfTest report' }
$p = Get-Content $selftest.FullName -Raw | ConvertFrom-Json
if ($p.outcome -ne 'PASS' -or $p.summary.PASS -ne 1 -or $p.lifecycle_actions_performed -ne 0) {
  throw 'UAT SelfTest report incorrect'
}
# GitHub runner has no isolated Host A task/runtime: fail CLOSED as BLOCKED,
# never test/live-control production or install anything on host A.
# Deliberate BLOCKED=exit 2 is not a product/CI failure here.
# GitHub Actions enables native-command errors by default in pwsh.
$PSNativeCommandUseErrorActionPreference = $false
& pwsh -NoProfile -File ./scripts/acceptance/issue86-pr89-uat.ps1 -Mode Preflight -OutputRoot $root
$blockedExit = $LASTEXITCODE
$PSNativeCommandUseErrorActionPreference = $true
if ($blockedExit -ne 2) { throw "UAT preflight did not fail closed without A: $blockedExit" }
$reports = @(Get-ChildItem -LiteralPath $root -Recurse -Filter report.json |
  ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json })
$preflight = @($reports | Where-Object { $_.metadata.mode -eq 'Preflight' })
if ($preflight.Count -ne 1 -or $preflight[0].outcome -ne 'BLOCKED' -or
    $preflight[0].lifecycle_actions_performed -ne 0 -or $preflight[0].summary.FAIL -ne 0) {
  throw 'UAT Preflight case classification is unsafe/inaccurate'
}
# Build the exact one-shot handoff package from the tested PR worktree.
# Prove the downloaded script works outside source using -WorktreeRoot.
$package = Join-Path $root 'package'
New-Item -ItemType Directory -Force -Path $package | Out-Null
Copy-Item ./scripts/acceptance/issue86-pr89-uat.ps1 (Join-Path $package 'issue86-pr89-uat.ps1')
Copy-Item ./scripts/acceptance/issue86-pr89-uat.README.md (Join-Path $package 'README.md')
Copy-Item ./scripts/acceptance/issue86-pr89-web-setup.ps1 (Join-Path $package 'setup-issue86-pr89-web.ps1')
& pwsh -NoProfile -File (Join-Path $package 'setup-issue86-pr89-web.ps1') -Mode SelfTest -OutputRoot $root
if ($LASTEXITCODE -ne 0) { throw 'Isolated PR89 Web Setup SelfTest failed' }
& pwsh -NoProfile -File (Join-Path $package 'issue86-pr89-uat.ps1') `
  -Mode SelfTest -WorktreeRoot $env:GITHUB_WORKSPACE -OutputRoot $root
if ($LASTEXITCODE -ne 0) { throw 'Downloaded one-shot UAT package failed SelfTest' }
# GitHub's pwsh wrapper propagates LASTEXITCODE even after checking it.
# Reset only CI's expected negative-test exit, not the UAT report.
$global:LASTEXITCODE = 0
exit 0

''',shell='pwsh')
    ctx.artifact(ctx.temp/'issue86-uat-runner')
