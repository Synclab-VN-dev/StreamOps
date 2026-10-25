[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Package,
  [Parameter(Mandatory=$true)][string]$Output,
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
if(!(Test-Path -LiteralPath $Package -PathType Leaf)) { throw 'Package does not exist' }
$arguments = @($tool, 'run', '--plan', $plan, '--package', $Package, '--output', $Output)
foreach($id in $Case) { $arguments += @('--case', $id) }
if($Resume) { $arguments += @('--resume', $Resume) }
& python @arguments
if($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
