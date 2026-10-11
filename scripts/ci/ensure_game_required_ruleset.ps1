# Issue #85 E2E-01 — protect master with the actual "windows" required check.
# This uses the operator's existing gh admin session. The GitHub connector
# cannot perform repository-administration PUT operations.
[CmdletBinding()]
param(
    [string]$Repository = 'Synclab-VN-dev/StreamOps',
    [int]$RulesetId = 24454446,
    [string]$RequiredContext = 'windows',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
if (!(Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI (gh) is required. Authenticate with an account allowed to update repository rulesets.'
}
$endpoint = "repos/$Repository/rulesets/$RulesetId"
$raw = & gh api $endpoint
if ($LASTEXITCODE -ne 0) { throw "Unable to read Ruleset $RulesetId. Verify gh auth status and repository permissions." }
$current = ($raw -join "`n") | ConvertFrom-Json -AsHashtable
if ($current.name -ne 'Master' -or $current.target -ne 'branch' -or $current.enforcement -ne 'active') {
    throw 'Unexpected ruleset name/target/enforcement; refusing to edit.'
}
if ('~DEFAULT_BRANCH' -notin @($current.conditions.ref_name.include)) {
    throw 'Ruleset does not cover the default branch; refusing to edit.'
}
$statusRules = @($current.rules | Where-Object { $_.type -eq 'required_status_checks' })
if ($statusRules.Count -ne 1) {
    throw 'Expected exactly one required_status_checks rule.'
}
$statusRule = $statusRules[0]
$checks = @($statusRule.parameters.required_status_checks)
if ($RequiredContext -in @($checks | ForEach-Object { $_.context })) {
    Write-Host "Verified: '$RequiredContext' already required by $Repository Ruleset $RulesetId"
    return
}
Write-Host "Ruleset $RulesetId currently requires: $(@($checks | ForEach-Object { $_.context }) -join ', ')"
if (!$Apply) {
    Write-Host "DRY RUN: would append required check '$RequiredContext' without changing any existing rule."
    Write-Host "To apply: .\scripts\ci\ensure_game_required_ruleset.ps1 -Apply"
    return
}
$check = @{ context = $RequiredContext }
$statusRule.parameters.required_status_checks = @($checks) + @($check)
# Never change enforcement, branch scope, bypass actors or other rules.
$payload = @{
    name = $current.name
    target = $current.target
    enforcement = $current.enforcement
    conditions = $current.conditions
    bypass_actors = @($current.bypass_actors)
    rules = @($current.rules)
}
$temp = New-TemporaryFile
try {
    $payload | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp.FullName -Encoding utf8
    & gh api --method PUT $endpoint --input $temp.FullName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'GitHub ruleset update failed' }
} finally {
    Remove-Item -LiteralPath $temp.FullName -ErrorAction SilentlyContinue
}
$verified = ((& gh api $endpoint) -join "`n") | ConvertFrom-Json -AsHashtable
if ($LASTEXITCODE -ne 0) { throw 'Could not verify updated ruleset' }
$required = @($verified.rules | Where-Object { $_.type -eq 'required_status_checks' })[0]
if ($RequiredContext -notin @($required.parameters.required_status_checks | ForEach-Object { $_.context })) {
    throw "Verification failed: '$RequiredContext' absent from required status checks"
}
if ($verified.enforcement -ne 'active' -or !$required.parameters.strict_required_status_checks_policy) {
    throw 'Verification failed: ruleset is not actively enforced in strict mode'
}
Write-Host "SUCCESS: '$RequiredContext' is now required on Master Ruleset $RulesetId"
