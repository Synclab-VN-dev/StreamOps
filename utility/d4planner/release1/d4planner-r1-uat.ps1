[CmdletBinding()]
param(
  [ValidateSet('Preflight','Automated','Resume','Report')][string]$Mode = 'Automated',
  [string]$Package,
  [Parameter(Mandatory=$true)][string]$Output,
  [string]$StagingRoot,
  [string]$EvidenceDirectory,
  [string]$ExpectedPackageSha256,
  [string]$ComponentManifest,
  [ValidateRange(1,65535)][int]$ApprovedTestPort,
  [string[]]$Case = @(),
  [string]$Resume,
  [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$tool = Join-Path (Split-Path -Parent $root) 'tools/release1_delivery.py'
$plan = Join-Path $root 'acceptance-plan.json'
if($SelfTest) {
  if(!(Test-Path -LiteralPath $tool -PathType Leaf)) { throw 'Missing Release 1 delivery tool' }
  if(!(Test-Path -LiteralPath $plan -PathType Leaf)) { throw 'Missing Release 1 acceptance plan' }
  Write-Host 'SELF_TEST_PASS'
  exit 0
}
if($Mode -eq 'Report') {
  if(!(Test-Path -LiteralPath $Output -PathType Leaf)) { throw 'Report does not exist' }
  & python $tool report --input $Output
  exit $LASTEXITCODE
}
if(!$Package -or !(Test-Path -LiteralPath $Package -PathType Leaf)) { throw 'Package does not exist' }
if(!$StagingRoot -or !$EvidenceDirectory -or !$ExpectedPackageSha256 -or !$ComponentManifest) {
  throw 'StagingRoot, EvidenceDirectory, ExpectedPackageSha256 and ComponentManifest are required'
}
$arguments = @(
  $tool, 'run', '--mode', $Mode, '--plan', $plan, '--package', $Package,
  '--output', $Output, '--staging-root', $StagingRoot,
  '--evidence-dir', $EvidenceDirectory, '--expected-package-sha256', $ExpectedPackageSha256,
  '--component-manifest', $ComponentManifest
)
if($ApprovedTestPort) { $arguments += @('--approved-port', [string]$ApprovedTestPort) }
foreach($id in $Case) { $arguments += @('--case', $id) }
if($Resume) { $arguments += @('--resume', $Resume) }
& python @arguments
if($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
