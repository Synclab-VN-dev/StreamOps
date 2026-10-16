# PR120/#119: one-shot isolated UAT setup; only starts missing NVDA.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ExpectedHead,
      [string]$Python='python',
      [string]$HomeDir=$(Join-Path $env:LOCALAPPDATA 'd4planner-issue119-pr120'),
      [string]$EvidenceDir='')
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$probe=Join-Path $PSScriptRoot 'issue119-probe.ps1'
if (!$EvidenceDir) {$EvidenceDir=Join-Path $env:TEMP ('d4planner-issue119-prepare-'+(Get-Date -Format yyyyMMdd-HHmmss))}
$EvidenceDir=[IO.Path]::GetFullPath($EvidenceDir)
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$report=[ordered]@{issue=119;mode='PrepareIsolated';status='BLOCKED';head='';checks=[ordered]@{};problems=@()}
function Gate([string]$id,[bool]$ok,[string]$why) {
  $result=if($ok){'PASS'}else{'BLOCKED'}
  $report.checks[$id]=[ordered]@{result=$result;detail=$why}
  Write-Host "[$result] $id - $why"
  if(!$ok){throw "$id - $why"}
}
function Native([string]$step,[string]$exe,[string[]]$argv) {
  $out=Join-Path $EvidenceDir ($step+'.stdout.txt')
  $err=Join-Path $EvidenceDir ($step+'.stderr.txt')
  & $exe @argv 1> $out 2> $err
  $code=$LASTEXITCODE
  [ordered]@{exe=$exe;args=$argv;exitCode=$code}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $EvidenceDir ($step+'.invocation.json')) -Encoding utf8
  if($code -ne 0) {
    $detail=[string](Get-Content $err -Raw -ErrorAction SilentlyContinue)
    throw "$step exited $code : $($detail.Substring(0,[Math]::Min(400,$detail.Length)))"
  }
}
try {
  Gate 'S0-01' (Test-Path -LiteralPath $probe -PathType Leaf) 'Read-only Preflight probe exists'
  $head=(& git -C $root rev-parse HEAD | Out-String).Trim()
  $report.head=$head
  Gate 'S0-02' ($head -eq $ExpectedHead -and $head -match '^[a-f0-9]{40}$') "Exact PR HEAD pinned: $head"
  $home=[IO.Path]::GetFullPath($HomeDir).TrimEnd('\')
  $prod=[IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'd4planner')).TrimEnd('\')
  Gate 'S0-03' (-not [string]::Equals($home,$prod,[StringComparison]::OrdinalIgnoreCase)) 'Isolated home differs from production'
  $steam=@(Get-Process -Name steam -ErrorAction SilentlyContinue)
  $game=@(Get-Process -Name 'Diablo IV' -ErrorAction SilentlyContinue)
  Gate 'S0-04' ($steam.Count -gt 0 -and $game.Count -gt 0) "Already-running Steam=$($steam.Count), DiabloIV=$($game.Count)"
  $env:D4PLANNER_HOME=$home
  $stateFile=Join-Path $home 'state/runtime.json'
  if(Test-Path -LiteralPath $stateFile){
    $prior=Get-Content $stateFile -Raw|ConvertFrom-Json
    if($prior.supervisorPid){
      $running=Get-Process -Id ([int]$prior.supervisorPid) -ErrorAction SilentlyContinue
      Gate 'S0-05' ($null -eq $running) "No live supervisor at previous PID $($prior.supervisorPid)"
    }
  }
  $venv=Join-Path $home 'uat-venv'
  $py=Join-Path $venv 'Scripts/python.exe'
  if(!(Test-Path $py -PathType Leaf)){Native 'venv-create' $Python @('-m','venv','--system-site-packages',$venv)}
  Gate 'S0-06' (Test-Path $py -PathType Leaf) 'Isolated UAT Python ready'
  Native 'venv-install' $py @('-m','pip','install','--no-deps','--no-build-isolation','-e',(Join-Path $root 'utility/d4planner'))
  Native 'cli-help' $py @('-m','d4planner.cli','start','--help')
  $helpText=Get-Content (Join-Path $EvidenceDir 'cli-help.stdout.txt') -Raw
  Gate 'S0-07' ($helpText.Contains('--uat-start-nvda')) 'PR120 CLI resolves in UAT venv'
  $env:PATH=(Join-Path $venv 'Scripts')+';'+$env:PATH
  Native 'uat-start' $py @('-m','d4planner.cli','start','-d','--isolated','--uat-start-nvda','--controller-profile','xbox16','--speech')
  $out=Join-Path $EvidenceDir 'preflight'
  New-Item -ItemType Directory -Force -Path $out|Out-Null
  & pwsh -NoProfile -ExecutionPolicy Bypass -File $probe -Mode Preflight -HomeDir $home -EvidenceDir $out -ExpectedHead $ExpectedHead
  Gate 'S0-08' ($LASTEXITCODE -eq 0) 'P0 real-A preflight PASS'
  $report.status='PASS'
}catch{
  $report.problems+=$_.Exception.Message
  Write-Warning $_.Exception.Message
}finally{
  $report|ConvertTo-Json -Depth 16|Set-Content -LiteralPath (Join-Path $EvidenceDir 'prepare-report.json') -Encoding utf8
  $zip="$EvidenceDir.zip"
  Compress-Archive -Path (Join-Path $EvidenceDir '*') -DestinationPath $zip -Force
  Write-Host "Issue119 prepare evidence: $zip"
  Write-Host "Status: $($report.status); Steam and Diablo IV unchanged."
}
if($report.status -ne 'PASS'){exit 2}
exit 0
