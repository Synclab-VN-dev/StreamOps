#requires -Version 7.0
<#
Issue #87 - One-command Real-A UAT for PR #95.
Safe default: -Mode Preflight does NOT start or stop anything.
Review requires -ApprovePlannerLifecycle. An isolated Session1 Scheduled Task
is created only if StreamOps-PR95-Manual does not already exist.
No Steam/OBS/Diablo IV/NVDA stop, restart, kill or Steam Input VDF change.
DF/MAN status is based on evidence, not synthetic marker provenance.
#>
[CmdletBinding()]
param(
  [ValidateSet('Preflight','Review')][string]$Mode='Preflight',
  [switch]$ApprovePlannerLifecycle,
  [switch]$RunLocalCI,
  [string]$Python='python',
  [string]$ExpectedHead='',
  [ValidateRange(15,180)][int]$StartTimeout=90,
  [string]$EvidenceDir=''
)
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$homeDir=Join-Path $root '.streamops/pr95/d4planner'
$taskName='StreamOps-PR95-Manual'
$reporter=Join-Path $root 'utility/d4planner/tools/issue87_uat_evidence.py'
# Always use PR95 checkout for relative local CI paths.
Push-Location $root
if (!$EvidenceDir) { $EvidenceDir=Join-Path $root ('.streamops/pr95/uat/real-'+(Get-Date -Format 'yyyyMMdd-HHmmss')) }
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$reportFile=Join-Path $EvidenceDir 'report.json'
$items=[ordered]@{}
foreach($group in @('DF','MAN')) {
  $last=if($group -eq 'DF'){14}else{8}
  foreach($n in 1..$last) {
    $id=('{0}-{1:D2}' -f $group,$n)
    $items[$id]=[ordered]@{id=$id;result='BLOCKED';expected='Acceptance per issue #87';actual='Not verified'}
  }
}
$logs=[System.Collections.Generic.List[object]]::new()
$failures=[System.Collections.Generic.List[string]]::new()
$manual=[ordered]@{}
$matrix=@()
$created=$false
$taskStarted=$false
$stopped=$false
$head=''
$sessionId=''
function Set-Result([string]$id,[string]$expected,[object]$actual,[string]$result) {
  if($result -notin @('PASS','FAIL','BLOCKED','SKIP')) {throw "Unknown result $result"}
  $items[$id]=[ordered]@{id=$id;expected=$expected;actual=$actual;result=$result}
}
function Run-Python([string]$name,[string[]]$argv) {
  $file=Join-Path $EvidenceDir ($name+'.log')
  & $Python @argv *> $file
  $code=$LASTEXITCODE
  $r=[ordered]@{name=$name;code=$code;log=$file}
  $logs.Add($r)
  return $r
}
function Prompt-Owner([string]$id,[string]$question) {
  do {$reply=(Read-Host "$id $question [Y/N/S=skip]").Trim().ToUpperInvariant()}
  until($reply -in @('Y','N','S'))
  $manual[$id]=$reply
  $grade=if($reply -eq 'Y'){'PASS'}elseif($reply -eq 'N'){'FAIL'}else{'BLOCKED'}
  Set-Result $id $question "Owner=$reply" $grade
}
function Current-Runtime {
  $p=Join-Path $homeDir 'state/runtime.json'
  if(!(Test-Path -LiteralPath $p -PathType Leaf)){return $null}
  try {return (Get-Content -LiteralPath $p -Raw|ConvertFrom-Json)}catch{return $null}
}
function Save-Evidence {
  $all=@($items.Values | ForEach-Object {$_})
  $summary=[ordered]@{}
  foreach($flag in @('PASS','FAIL','BLOCKED','SKIP')) {$summary[$flag]=@($all|Where-Object {$_.result -eq $flag}).Count}
  [ordered]@{
    schemaVersion=1;ticket=87;pr=95;mode=$Mode;head=$head
    generatedAt=(Get-Date).ToUniversalTime().ToString('o')
    home=$homeDir;task=$taskName;taskCreatedByScript=$created
    taskStartedByScript=$taskStarted;stoppedSafely=$stopped
    sessionId=$sessionId;summary=$summary;checks=$all
    logs=$logs.ToArray();manualAnswers=$manual;physicalMatrix=$matrix
    errors=$failures.ToArray();evidenceDir=$EvidenceDir
    warning='PASS of keyboard marker does not prove physical controller. No auto-merge.'
  } | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $reportFile -Encoding utf8
}
function Stop-OwnedTask {
  if(!$created){return}
  if($taskStarted){
    $p=Join-Path $homeDir 'state/stop.request'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $p)|Out-Null
    'stop'|Set-Content -LiteralPath $p -Encoding ascii
    $deadline=(Get-Date).AddSeconds(25)
    do {
      $r=Current-Runtime
      if($r -and $r.state -eq 'STOPPED'){$stopped=$true;break}
      Start-Sleep -Milliseconds 200
    }while((Get-Date) -lt $deadline)
    if(!$stopped){
      $failures.Add('Supervisor did not acknowledge STOPPED; leave task intact for diagnosis. No force-kill.')
      return
    }
  }else{$stopped=$true}
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
  $created=$false
}
try {
  $head=(& git -C $root rev-parse HEAD).Trim()
  $branchName=(& git -C $root branch --show-current).Trim()
  if($branchName -ne 'feat/87-xbox16-multikey-capture' -or ($ExpectedHead -and $head -ne $ExpectedHead)){
    throw "Wrong PR worktree or HEAD: $branchName / $head"
  }
  if(!(Test-Path $reporter)){throw "Missing reporter: $reporter"}
  if(!(Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)){throw 'Windows A PowerShell required'}
  $listeners=@(Get-NetTCPConnection -LocalPort 18795 -State Listen -ErrorAction SilentlyContinue)
  if($listeners.Count){throw "Port 18795 already listening, PID(s): $(@($listeners|ForEach-Object {$_.OwningProcess}) -join ',')"}
  if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){
    throw "Task $taskName already exists; never overwrite it"
  }
  if(Test-Path (Join-Path $homeDir 'state/supervisor.lock')){
    throw 'Dedicated PR95 DataDir has a supervisor lock; refusing reuse'
  }
  $steam=@(Get-Process -Name steam -ErrorAction SilentlyContinue)
  $game=@(Get-Process -Name 'Diablo IV' -ErrorAction SilentlyContinue)
  $nvda=@(Get-Process -ErrorAction SilentlyContinue|Where-Object {$_.ProcessName -match '^nvda'})
  $obs=@(Get-Process -Name obs64 -ErrorAction SilentlyContinue)
  $baseline=[ordered]@{
    windows=[Environment]::OSVersion.VersionString
    session=(Get-Process -Id $PID).SessionId
    languages=@(Get-WinUserLanguageList|ForEach-Object {$_.LanguageTag})
    steam=@($steam|ForEach-Object {$_.Id})
    game=@($game|ForEach-Object {$_.Id})
    nvda=@($nvda|ForEach-Object {$_.Id})
    obs=@($obs|ForEach-Object {$_.Id})
    python=(& $Python --version 2>&1|Out-String).Trim()
    gitHead=$head;branch=$branchName
  }
  Set-Result 'DF-01' 'Exact PR SHA, host, session, process and language snapshot' $baseline 'PASS'
  # Optional dependency mutation is explicit. Default preflight only reads.
  if($RunLocalCI){
    $install=Run-Python 'local-pip' @('-m','pip','install','-e','utility/d4planner[dev]')
    $unit=Run-Python 'local-pytest' @('-m','pytest','-q','utility/d4planner/tests')
    $compile=Run-Python 'local-compile' @('-m','compileall','-q','utility/d4planner')
    $addon=Run-Python 'local-addon-build' @('utility/d4planner/tools/build_nvda_addon.py')
    $good=($install.code -eq 0 -and $unit.code -eq 0 -and $compile.code -eq 0 -and $addon.code -eq 0)
    Set-Result 'DF-02' 'Local full pytest/compile/addon build' @{install=$install;unit=$unit;compile=$compile;addon=$addon} $(if($good){'PASS'}else{'FAIL'})
    if(!$good){throw 'Local CI failed; no supervisor started'}
  }
  $installed=Run-Python 'module-path' @('-c','import d4planner;print(d4planner.__file__)')
  $expected=Join-Path $root 'utility/d4planner/src/d4planner/__init__.py'
  if($installed.code -ne 0){throw 'D4Planner package not installed; run -RunLocalCI'}
  $resolved=(Get-Content $installed.log -Raw).Trim()
  if([IO.Path]::GetFullPath($resolved) -ine [IO.Path]::GetFullPath($expected)){
    throw "D4Planner Python package is not from PR95 worktree: $resolved. Run -RunLocalCI"
  }
  $valid=Run-Python 'controller-validate' @('-m','d4planner.cli','controller','validate','xbox16')
  $profiles=Run-Python 'controller-profiles' @('-m','d4planner.cli','controller','profiles')
  $ok=($valid.code -eq 0 -and $profiles.code -eq 0)
  Set-Result 'DF-03' 'Profile/contract CLI exit zero' @{profiles=$profiles;validation=$valid} $(if($ok){'PASS'}else{'FAIL'})
  if(!$ok){throw 'Controller CLI validation failed'}
  if($Mode -eq 'Preflight'){Write-Host 'Read-only preflight passed.'}
  else {
    if(!$ApprovePlannerLifecycle){throw 'Review requires -ApprovePlannerLifecycle'}
    if($game.Count -ne 1 -or !$steam.Count -or !$nvda.Count){throw 'Require already-running Steam + D4 + NVDA; no auto-launch'}
    $gameSession=$game[0].SessionId
    if($gameSession -le 0 -or !@($nvda|Where-Object {$_.SessionId -eq $gameSession}).Count){
      throw 'Game/NVDA must share interactive Session 1'
    }

    $exe=(Get-Command $Python -ErrorAction Stop).Source
    if(!(Test-Path -LiteralPath $exe -PathType Leaf)){throw 'Python must resolve to a real exe'}
    New-Item -ItemType Directory -Force -Path $homeDir|Out-Null
    $argsText='-m d4planner.daemon --isolated --block --controller-profile xbox16 --uat-attach-only --home "'+$homeDir+'"'
    $action=New-ScheduledTaskAction -Execute $exe -Argument $argsText
    $user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -Priority 4 -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $task=New-ScheduledTask -Action $action -Principal $principal -Settings $settings
    Register-ScheduledTask -TaskName $taskName -InputObject $task -ErrorAction Stop|Out-Null
    $created=$true
    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $taskStarted=$true
    $until=(Get-Date).AddSeconds($StartTimeout)
    $ready=$false
    do {
      $runtime=Current-Runtime
      if($runtime -and $runtime.state -in @('BLOCKED','RESTART_REQUIRED','STOPPED')){
        throw "Startup failed: $($runtime.state), $($runtime.lastError)"
      }
      if($runtime -and $runtime.state -eq 'RUNNING' -and
          $runtime.extras.inputMarker.state -eq 'ACTIVE' -and
          $runtime.extras.inputMarker.mode -eq 'BLOCK' -and
          $runtime.extras.inputMarker.layoutId -eq 'xbox-steaminput-18-v1' -and
          $runtime.extras.inputMarker.sessionId -eq $gameSession){
        $ready=$true;$sessionId=[string]$runtime.sessionId;break
      }
      Start-Sleep -Milliseconds 350
    }while((Get-Date) -lt $until)
    Set-Result 'DF-04' 'Isolated Xbox16 BLOCK ACTIVE in D4 Session1' $runtime $(if($ready){'PASS'}else{'FAIL'})
    if(!$ready){throw 'Hook not ready before timeout'}
    $startEvidence=Join-Path $EvidenceDir 'start.json'
    $capture=Run-Python 'capture-start' @($reporter,'--home',$homeDir,'--mode','snapshot','--out',$startEvidence)
    if($capture.code -ne 0){throw 'Capture baseline invalid'}
    Write-Host 'Press/release all 16 physical controller buttons on C via Steam Link, keeping Diablo IV foreground.'
    Read-Host 'When finished, press ENTER here to collect evidence'
    $resultPath=Join-Path $EvidenceDir 'capture.json'
    $analysis=Run-Python 'capture-end' @($reporter,'--home',$homeDir,'--mode','analyze','--start',$startEvidence,'--out',$resultPath)
    if(Test-Path $resultPath){$data=Get-Content $resultPath -Raw|ConvertFrom-Json;$matrix=@($data.matrix)}
    $goodMarkers=@($matrix|Where-Object {$_.result -eq 'PASS'}).Count
    Set-Result 'DF-08' 'SQLite integrity, marker streams and speech observations' @{report=$resultPath;exitCode=$analysis.code} $(if($analysis.code -eq 0){'PASS'}else{'FAIL'})
    Write-Host "Automatic keyboard marker matrix: $goodMarkers/16. Physical origin requires your confirmation."
    Prompt-Owner 'MAN-01' 'Steam Input bindings and four punctuation mappings are correct?'
    Prompt-Owner 'MAN-02' 'Status shows correct BLOCK/ACTIVE 16-key Session1?'
    Prompt-Owner 'MAN-03' 'All 16 physical keys came from controller C, with gamepad retained?'
    Prompt-Owner 'MAN-04' 'Gameplay, LT/RT and F10/F11 overlay have no regression/blink?'
    Prompt-Owner 'MAN-05' 'Blocking physical mapped keyboard keys is acceptable; other keys/apps unaffected?'
    Prompt-Owner 'MAN-06' 'Speech and input raw/pretty logs are usable and preserved?'
    Set-Result 'DF-05' 'Steam Input visual binding verified' $manual['MAN-01'] $items['MAN-01'].result
    Set-Result 'DF-06' 'All 16 physical buttons and marker DOWN/UP' @{markerPass=$goodMarkers;owner=$manual['MAN-03'];matrix=$resultPath} $(if($goodMarkers -eq 16 -and $manual['MAN-03'] -eq 'Y'){'PASS'}elseif($goodMarkers -lt 16){'FAIL'}else{'BLOCKED'})
    Set-Result 'DF-07' 'Gamepad and cursor/gameplay physically checked' $manual['MAN-04'] $items['MAN-04'].result
    Set-Result 'DF-09' 'Physical keyboard/window and F10 hotkey checked' $manual['MAN-05'] $items['MAN-05'].result
    $endStatus=Current-Runtime
    Set-Result 'DF-10' 'Queue 0 dropped; stress/hold must also be observed' $endStatus.extras.inputMarker 'BLOCKED'
  }
}catch{
  $failures.Add(($_.Exception.Message+' | '+$_.ScriptStackTrace))
}finally{
  if($created){
    $stop=Join-Path $homeDir 'state/stop.request'
    if($taskStarted){
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stop)|Out-Null
      'stop'|Set-Content -LiteralPath $stop -Encoding ascii
      $deadline=(Get-Date).AddSeconds(25)
      do {
        $runtime=Current-Runtime
        if($runtime -and $runtime.state -eq 'STOPPED'){$stopped=$true;break}
        Start-Sleep -Milliseconds 200
      }while((Get-Date) -lt $deadline)
    }else{$stopped=$true}
    if($stopped){
      try{Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop;$created=$false}
      catch{$failures.Add("Task cleanup: $($_.Exception.Message)")}
    }else{$failures.Add('Stop unconfirmed; PR95 task retained for diagnosis, no force kill')}
    Set-Result 'DF-13' 'Owned task cleaned after acknowledged stop; existing services untouched' @{stopped=$stopped;task=$taskName} $(if($stopped -and !$created){'PASS'}else{'BLOCKED'})
  }
  if($Mode -eq 'Review'){
    Set-Result 'DF-11' 'Legacy Real-A observe and block rounds' 'Additional approved round required' 'BLOCKED'
    Set-Result 'DF-12' 'No hook after stop, physical keyboard restored' @{stopped=$stopped} 'BLOCKED'
    Set-Result 'DF-14' 'Report/evidence uploaded to PR and ticket' $reportFile 'BLOCKED'
    if($taskStarted -and $ready){
      Prompt-Owner 'MAN-07' 'After stop, keyboard restored and Steam/Diablo IV still running?'
      Prompt-Owner 'MAN-08' 'Approve V1 16 digital, LT/RT threshold, two analog reserved (GO/NO-GO)?'
    }
    if($stopped -and $manual['MAN-07'] -eq 'Y'){
      Set-Result 'DF-12' 'Stop restored physical mapped keyboard keys' 'Owner confirmed' 'PASS'
    }
  }
  Save-Evidence
  Write-Host "Issue #87 report: $reportFile"
  $report=Get-Content $reportFile -Raw|ConvertFrom-Json
  Write-Host ("PASS={0} FAIL={1} BLOCKED={2} SKIP={3}" -f $report.summary.PASS,$report.summary.FAIL,$report.summary.BLOCKED,$report.summary.SKIP)
  foreach($errorText in $failures){Write-Host "BLOCKER: $errorText"}
  Pop-Location
}
