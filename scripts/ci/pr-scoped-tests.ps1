#requires -Version 7.0
[CmdletBinding()]
param([string]$BaseSha,[string]$HeadSha,[switch]$SelfTest)
$ErrorActionPreference = 'Stop'

function Scope-For([string[]]$files) {
  $d4=$false; $server=$false; $fe=$false; $unknown=@()
  foreach($file in $files) {
    $p=$file.Replace('\','/').ToLowerInvariant()
    if($p -like 'utility/d4planner/*' -or $p -like 'scripts/acceptance/issue119*' -or $p -like 'scripts/acceptance/issue87*') {$d4=$true;continue}
    if($p -like 'streamops/server/web/*' -or $p -like 'streamops/server/tests/visual_magicpath/*' -or
       $p -like 'streamops/server/tests/test_magicpath_visual_contract.py' -or
       $p -like 'streamops/server/tests/test_games_ui_contract.py' -or
       $p -like 'streamops/server/tests/e2e/test_games_ui.py' -or
       $p -like 'streamops/server/tests/e2e/test_games_fe_be_integration.py' -or
       $p -like 'streamops/server/tests/e2e/test_steam.py') {$fe=$true;continue}
    if($p -like 'streamops/*' -or $p -like 'scripts/ci/*game*' -or $p -like 'scripts/e2e/issue85*' -or
       $p -like 'scripts/devices/a-windows/issue85*') {$server=$true;continue}
    if($p -eq 'pyproject.toml') {$d4=$true;$server=$true;$fe=$true;continue}
    if($p -like 'utility/d4-rulekit/*' -or $p -like 'utility/d4planner-overlay-poc/*' -or
       $p -like 'scripts/local/d4-overlay-poc*' -or $p -like 'scripts/e2e/d4-overlay-poc*' -or
       $p -like '.github/workflows/*' -or $p -eq 'scripts/ci/pr-scoped-tests.ps1' -or
       $p -like 'docs/*' -or $p -like '*.md' -or $p -like '.git*') {continue}
    $unknown+= $file
  }
  if($unknown.Count) {throw "Unclassified source paths: $($unknown -join ', ')"}
  return [pscustomobject]@{D4=$d4;Server=$server;FE=$fe}
}

if($SelfTest) {
  $checks=@(
    @{paths=@('utility/d4planner/src/x.py','.github/workflows/pr-tests.yml');expected='100'},
    @{paths=@('scripts/acceptance/issue119-probe.ps1');expected='100'},
    @{paths=@('streamops/server/tests/test_obs.py');expected='010'},
    @{paths=@('streamops/server/web/games.js');expected='001'},
    @{paths=@('utility/d4planner/tests/a.py','streamops/server/api.py');expected='110'},
    @{paths=@('pyproject.toml');expected='111'},
    @{paths=@('utility/d4-rulekit/src/x.py');expected='000'}
  )
  foreach($check in $checks) {
    $scope=Scope-For $check.paths
    $actual=([int]$scope.D4).ToString()+([int]$scope.Server)+([int]$scope.FE)
    if($actual -ne $check.expected) {throw "Routing mismatch $($check.paths -join ','): $actual"}
  }
  Write-Host 'SCOPING PASS: 7/7 cases'
  exit 0
}
if(!$BaseSha -or !$HeadSha) {throw 'Missing immutable base/head SHA'}
$files=@(& git diff --name-only "$BaseSha...$HeadSha")
if($LASTEXITCODE -ne 0 -or $files.Count -eq 0) {throw 'Cannot calculate PR changed files'}
$scope=Scope-For $files
$modules=@()
if($scope.D4) {$modules+='D4Planner'}
if($scope.Server) {$modules+='StreamOpsServer'}
if($scope.FE) {$modules+='StreamOpsFE'}
Write-Host "SCOPED MODULES: $($modules -join ', ')"
$files | ForEach-Object {Write-Host "  $_"}
function Invoke-CheckedCI([string]$cmd,[string[]]$argv) {
  $script:invokedTests++
  Write-Host "CI COMMAND: $cmd $($argv -join ' ')"
  & $cmd @argv
  if($LASTEXITCODE -ne 0) {throw "$cmd $($argv -join ' ') failed, exit=$LASTEXITCODE"}
}
$script:invokedTests=0
$report=[ordered]@{base=$BaseSha;head=$HeadSha;modules=$modules;result='FAIL';testCommands=0}
try {
  if($modules -contains 'D4Planner') {
    Write-Host 'START D4PLANNER TESTS'
    Invoke-CheckedCI python @('-m','pip','install','-e','utility/d4planner[dev]')
    Invoke-CheckedCI python @('-m','pytest','-q','utility/d4planner/tests')
    Invoke-CheckedCI python @('-m','d4planner.cli','controller','validate','xbox16')
    Invoke-CheckedCI python @('utility/d4planner/tools/build_nvda_addon.py')
    $w=Join-Path $env:RUNNER_TEMP 'd4planner-wheel'
    New-Item -ItemType Directory -Path $w -Force | Out-Null
    Invoke-CheckedCI python @('-m','pip','wheel','--no-deps','-w',$w,'utility/d4planner')
  }
  if($modules -contains 'StreamOpsServer' -or $modules -contains 'StreamOpsFE') {
    Invoke-CheckedCI python @('-m','pip','install','.[server,dev]')
  }
  if($modules -contains 'StreamOpsServer') {
    Invoke-CheckedCI python @('-m','playwright','install','chromium')
    Invoke-CheckedCI python @('-m','pytest','-q','streamops/server/tests')
  } elseif($modules -contains 'StreamOpsFE') {
    Invoke-CheckedCI python @('-m','playwright','install','chromium')
    Invoke-CheckedCI python @('-m','pytest','-q',
      'streamops/server/tests/test_games_ui_contract.py',
      'streamops/server/tests/test_magicpath_visual_contract.py',
      'streamops/server/tests/e2e/test_games_ui.py',
      'streamops/server/tests/e2e/test_games_fe_be_integration.py',
      'streamops/server/tests/e2e/test_steam.py')
  }
  if($modules.Count -gt 0 -and $script:invokedTests -eq 0) {
    throw 'CI FALSE GREEN: module selected but no test command ran'
  }
  $report.testCommands=$script:invokedTests
  $report.result='PASS'
} finally {
  if($env:RUNNER_TEMP) {
    $report | ConvertTo-Json -Depth 8 |
      Set-Content -Path (Join-Path $env:RUNNER_TEMP 'pr-scoped-tests.json') -Encoding utf8
  }
}
