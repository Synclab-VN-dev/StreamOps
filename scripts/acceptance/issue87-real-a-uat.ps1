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
$reporter=Join-Path $root 'utility/d4planner/d4planner-be/tools/issue87_uat_evidence.py'
$sourceRoot=Join-Path $root 'utility/d4planner/d4planner-be/src'
$venvDir=Join-Path $root '.streamops/pr95/python-venv'
$probePython=$Python
$originalPythonPath=$env:PYTHONPATH
$runtimePython=$null
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
  # The caller may have installed D4Planner editable from an unrelated
  # worktree (#82). Put this SHA-pinned PR95 source ahead of site-packages
  # for this child process ONLY. Never mutate global pip or user PYTHONPATH.
  $oldPythonPath=$env:PYTHONPATH
  $oldPath=$env:PATH
  try {
    $env:PYTHONPATH=$sourceRoot
    # Commands spawned by tests (for example shutil.which('d4planner')) must
    # resolve only the isolated venv entrypoints, never a global installation.
    $venvBin=Split-Path -Parent $script:probePython
    $env:PATH=$venvBin+[IO.Path]::PathSeparator+$oldPath
    & $script:probePython @argv *> $file
    $code=$LASTEXITCODE
  } finally {
    $env:PYTHONPATH=$oldPythonPath
    $env:PATH=$oldPath
  }
  $command=@($script:probePython)+@($argv)
  $r=[ordered]@{
    name=$name;code=$code;log=$file;python=$script:probePython;source=$sourceRoot
    command=$command;classification='UNCLASSIFIED'
  }
  $logs.Add($r)
  return $r
}
function Get-LocalPytestClassification([object]$run) {
  if($run.code -eq 0){return 'PASS'}
  $text=if(Test-Path -LiteralPath $run.log -PathType Leaf){Get-Content -LiteralPath $run.log -Raw}else{''}
  if($text -match 'ModuleNotFoundError|DistributionNotFound|pkg_resources\.DistributionNotFound'){
    return 'DEPENDENCY_FAILURE'
  }
  if($run.code -eq 2){return 'HARNESS_FAILURE'}
  return 'PRODUCT_FAILURE'
}
function Write-LocalPytestFailure([object]$run) {
  if($run.code -eq 0 -or !(Test-Path -LiteralPath $run.log -PathType Leaf)){return}
  # This log contains only the local pytest command output; never dump process
  # environment, credentials, bootstrap tokens or other runtime evidence.
  Write-Host "::group::local-pytest failure (exit=$($run.code), classification=$($run.classification))"
  Get-Content -LiteralPath $run.log | ForEach-Object {Write-Host $_}
  Write-Host '::endgroup::'
}
function Ensure-PR-Python {
  # Review/local CI requires a process image that persists our PR95 package
  # when launched by Windows Task Scheduler (no inherited caller PYTHONPATH).
  # All writes remain inside the PR95 worktree; pip global remains untouched.
  $venvPython=Join-Path $venvDir 'Scripts/python.exe'
  if(!(Test-Path -LiteralPath $venvPython -PathType Leaf)){
    New-Item -ItemType Directory -Force -Path $venvDir | Out-Null
    $creationLog=Join-Path $EvidenceDir 'pr95-venv-create.log'
    & $Python -m venv $venvDir *> $creationLog
    if($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $venvPython -PathType Leaf)){
      throw "Cannot create isolated PR95 Python venv; see $creationLog"
    }
    $logs.Add([ordered]@{name='pr95-venv-create';code=0;log=$creationLog;python=$Python})
  }
  $purelib=@(& $venvPython -c 'import sysconfig;print(sysconfig.get_path("purelib"))')
  if($LASTEXITCODE -ne 0 -or $purelib.Count -ne 1 -or ![string]$purelib[0]){
    throw 'Cannot find PR95 venv site-packages'
  }
  $pth=Join-Path -Path (([string]$purelib[0]).Trim()) -ChildPath 'streamops-pr95-source.pth'
  if(Test-Path -LiteralPath $pth){
    $oldPath=(Get-Content -LiteralPath $pth -Raw).Trim()
    if($oldPath -ine $sourceRoot){throw "PR95 venv points to another checkout: $oldPath"}
  }else{
    $sourceRoot | Set-Content -LiteralPath $pth -Encoding utf8
  }
  $resolved=@(& $venvPython -I -c 'import d4planner;print(d4planner.__file__)')
  $expected=Join-Path $sourceRoot 'd4planner/__init__.py'
  if($LASTEXITCODE -ne 0 -or $resolved.Count -ne 1 -or
      [IO.Path]::GetFullPath(([string]$resolved[0]).Trim()) -ine [IO.Path]::GetFullPath($expected)){
    throw 'PR95 isolated venv cannot resolve this exact checkout'
  }
  $script:probePython=$venvPython
  $script:runtimePython=$venvPython
  $logs.Add([ordered]@{name='pr95-venv-verify';code=0;python=$venvPython;source=$expected})
}
function Prompt-Owner([string]$id,[string]$question) {
  # Only an informed review of this exact Vietnamese question is evidence.
  # Y is never a blanket approval for the whole UAT/PR.
  Write-Host "$id - $question"
  do {$reply=(Read-Host 'Y=Da tu kiem tra va dung; N=Khong dung; S=Chua kiem tra (giu BLOCKED)').Trim().ToUpperInvariant()}
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
  $headOutput = & git -C $root rev-parse HEAD
  if ($LASTEXITCODE -ne 0 -or -not $headOutput) {
    throw 'Cannot determine checked-out Git HEAD'
  }
  $head = ([string]$headOutput).Trim()
  # A SHA-pinned PR95 worktree uses detached HEAD by design. Git prints no
  # branch name in that case (PowerShell returns $null, not an empty string).
  $branchOutput = & git -C $root branch --show-current
  if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect checked-out Git branch' }
  $branchName = if ($null -eq $branchOutput) { '' } else {
    ([string]$branchOutput).Trim()
  }
  $branchOK = $branchName -eq 'feat/87-xbox16-multikey-capture'
  # Owner can safely review a detached, immutable worktree pinned by SHA.
  if(!$branchOK -and $branchName -eq '' -and $ExpectedHead -eq $head) {
    $branchOK=$true
  }
  if(!$branchOK -or ($ExpectedHead -and $head -ne $ExpectedHead)){
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
  # WinRT-backed Get-WinUserLanguageList can fail with marshalling errors
  # under PowerShell 7 on Windows A. CultureInfo and registry are read-only.
  $cultureName = [System.Globalization.CultureInfo]::CurrentCulture.Name
  $uiCultureName = [System.Globalization.CultureInfo]::CurrentUICulture.Name
  $keyboardLayouts = @()
  $keyboardLayoutError = $null
  $preload = $null
  try {
    $preload = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Keyboard Layout\Preload', $false)
    if ($null -ne $preload) {
      foreach ($slot in @($preload.GetValueNames() | Where-Object { $_ -match '^\d+$' } | Sort-Object { [int]$_ })) {
        $keyboardLayouts += [ordered]@{
          slot = [string]$slot
          klid = [string]$preload.GetValue($slot)
        }
      }
    } else {
      $keyboardLayoutError = 'HKCU keyboard layout preload key not found'
    }
  } catch {
    $keyboardLayoutError = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
  } finally {
    if ($null -ne $preload) { $preload.Dispose() }
  }
  $baseline=[ordered]@{
    windows=[Environment]::OSVersion.VersionString
    session=(Get-Process -Id $PID).SessionId
    languages=@($cultureName,$uiCultureName | Where-Object { $_ } | Select-Object -Unique)
    userCulture=$cultureName
    uiCulture=$uiCultureName
    keyboardLayoutPreload=$keyboardLayouts
    keyboardLayoutNote='HKCU configured preload entries, not active physical keyboard layout'
    keyboardLayoutError=$keyboardLayoutError
    steam=@($steam|ForEach-Object {$_.Id})
    game=@($game|ForEach-Object {$_.Id})
    nvda=@($nvda|ForEach-Object {$_.Id})
    obs=@($obs|ForEach-Object {$_.Id})
    python=(& $Python --version 2>&1|Out-String).Trim()
    sourceScope=$sourceRoot
    effectivePython=$probePython
    gitHead=$head;branch=$branchName
  }
  Set-Result 'DF-01' 'Exact PR SHA, host, session, process and language snapshot' $baseline 'PASS'
  # Optional dependency mutation is explicit. Default preflight only reads.
  if($RunLocalCI){
    Ensure-PR-Python
    # Install this checkout plus its declared dev dependency set only in the
    # PR95 venv. Do not duplicate individual packages or mutate global Python.
    $install=Run-Python 'local-pr95-dev-install' @(
      '-m','pip','install','--editable','utility/d4planner/d4planner-be[dev]'
    )
    $install['classification']=if($install.code -eq 0){'PASS'}else{'DEPENDENCY_FAILURE'}
    if($install.code -ne 0){throw 'Cannot install D4Planner dev dependencies in PR95 isolated venv'}
    # pip may replace editable metadata; verify -I still resolves this exact
    # worktree and refuses a foreign editable checkout after installation.
    Ensure-PR-Python
    $dependencyImport=Run-Python 'local-pr95-dependency-import' @(
      '-c','import jsonschema, referencing; from importlib.metadata import version; print(version("jsonschema")); print(referencing.__file__)'
    )
    $dependencyImport['classification']=if($dependencyImport.code -eq 0){'PASS'}else{'DEPENDENCY_FAILURE'}
    $pipCheck=Run-Python 'local-pr95-pip-check' @('-m','pip','check')
    $pipCheck['classification']=if($pipCheck.code -eq 0){'PASS'}else{'DEPENDENCY_FAILURE'}
    $unit=Run-Python 'local-pytest' @('-m','pytest','-q','utility/d4planner/d4planner-be/tests')
    $unit['classification']=Get-LocalPytestClassification $unit
    Write-LocalPytestFailure $unit
    $compile=Run-Python 'local-compile' @('-m','compileall','-q','utility/d4planner/d4planner-be')
    $addon=Run-Python 'local-addon-build' @('utility/d4planner/d4planner-be/tools/build_nvda_addon.py')
    $good=($dependencyImport.code -eq 0 -and $pipCheck.code -eq 0 -and
      $unit.code -eq 0 -and $compile.code -eq 0 -and $addon.code -eq 0)
    Set-Result 'DF-02' 'Local full pytest/compile/addon build in isolated PR95 venv' @{
      install=$install;dependencyImport=$dependencyImport;pipCheck=$pipCheck
      unit=$unit;compile=$compile;addon=$addon
    } $(if($good){'PASS'}else{'FAIL'})
    if(!$good){throw 'Local CI failed; no supervisor started'}
  }
  $installed=Run-Python 'module-path' @('-c','import d4planner;print(d4planner.__file__)')
  $expected=Join-Path $sourceRoot 'd4planner/__init__.py'
  if($installed.code -ne 0){throw "Cannot import PR95 D4Planner via source-scoped PYTHONPATH; see $($installed.log)"}
  $resolved=(Get-Content -LiteralPath $installed.log -Raw).Trim()
  if([IO.Path]::GetFullPath($resolved) -ine [IO.Path]::GetFullPath($expected)){
    throw "PR95 Python import isolation violated: expected $expected, observed $resolved"
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

    # Scheduled Tasks do not inherit the SSH caller's PYTHONPATH. Create/verify
    # a separate PR95 virtualenv so the detached daemon cannot import #82.
    Ensure-PR-Python
    $exe=$runtimePython
    if(!(Test-Path -LiteralPath $exe -PathType Leaf)){throw 'PR95 isolated Python interpreter is unavailable'}
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
    Write-Host 'Tren dien thoai C/Steam Link: giu Diablo IV la cua so dang mo; bam va tha tung nut trong 16 nut controller. Co the bam nhieu lan moi nut.'
    Write-Host 'Trong game, mo Inventory va dua con tro vao trang bi de thu speech NVDA; neu khong co speech, muc speech se BLOCKED.'
    Read-Host 'Khi da thu xong, nhan ENTER de thu thap bang chung'
    $resultPath=Join-Path $EvidenceDir 'capture.json'
    $analysis=Run-Python 'capture-end' @($reporter,'--home',$homeDir,'--mode','analyze','--start',$startEvidence,'--out',$resultPath)
    if(Test-Path $resultPath){$data=Get-Content $resultPath -Raw|ConvertFrom-Json;$matrix=@($data.matrix)}
    $goodMarkers=@($matrix|Where-Object {$_.result -eq 'PASS'}).Count
    # Capture the same CLI reader surfaces the owner will inspect.
    $previousHome=$env:D4PLANNER_HOME
    try {
      $env:D4PLANNER_HOME=$homeDir
      $fullLog=Run-Python 'logs-raw-all' @('-m','d4planner.cli','logs','--raw')
      $inputLog=Run-Python 'logs-raw-input' @('-m','d4planner.cli','logs','--input','--raw')
      $prettyLog=Run-Python 'logs-pretty-input' @('-m','d4planner.cli','logs','--input')
    } finally {$env:D4PLANNER_HOME=$previousHome}
    $speechCount=if($data){[int]$data.speechEvents}else{0}
    $logsOk=($fullLog.code -eq 0 -and $inputLog.code -eq 0 -and $prettyLog.code -eq 0)
    # The analyzer exit 2 can be caused solely by DF-06 marker mismatches.
    # Do not misclassify canonical DB/log health as product failure for that.
    $integrityFails=if($data){@($data.checks|Where-Object {$_.result -eq 'FAIL'})}else{@('capture.json missing')}
    $dbState=if(!$logsOk -or $integrityFails.Count){'FAIL'}elseif($speechCount -eq 0){'BLOCKED'}else{'PASS'}
    Set-Result 'DF-08' 'Canonical SQLite + raw/pretty CLI input; speech retained when observed' @{
      analyzer=$resultPath;exitCode=$analysis.code;speechEvents=$speechCount
      integrityFailures=@($integrityFails);full=$fullLog;input=$inputLog;pretty=$prettyLog
    } $dbState
    Write-Host "Ma tran phim: $goodMarkers/16 nut PASS. Day la tin hieu keyboard, khong tu chung minh nguon controller C."
    Write-Host 'Chi tra loi Y NEU ANH DA THUC SU KIEM TRA noi dung cau hoi. Neu khong chac, chon S.'
    Prompt-Owner 'MAN-01' 'Anh da xem layout Steam Input, thay dung 16 mapping (gom 4 phim dau cau) va giu mapping gamepad goc?'
    Prompt-Owner 'MAN-02' 'Trang thai PR95 RUNNING; inputMarker ACTIVE, BLOCK, xbox-steaminput-18-v1, Session 1, digital=16, dropped=0?'
    Prompt-Owner 'MAN-03' 'Anh THUC SU nhan nut controller C/Steam Link; ca 16 nut co DOWN/UP va gamepad goc van hoat dong?'
    Prompt-Owner 'MAN-04' 'Anh da choi thu, test LT/RT, F10/F11, overlay va khong thay giat/nhay con tro hay loi gameplay?'
    Prompt-Owner 'MAN-05' 'Anh da test phim ban phim vat ly, cua so khac, BLOCK chi anh huong phim map trong D4 va chap nhan gioi han nay?'
    Prompt-Owner 'MAN-06' 'Anh da xem log input raw/pretty va speech NVDA, xac nhan du, dung, de doc va duoc luu?' 
    if($goodMarkers -ne 16 -and $items['MAN-03'].result -eq 'PASS'){
      Set-Result 'MAN-03' 'Controller C source & full 16 digital edge evidence' 'Khong du 16 marker hop le; khong the PASS MAN-03' 'BLOCKED'
    }
    if($dbState -ne 'PASS' -and $items['MAN-06'].result -eq 'PASS'){
      Set-Result 'MAN-06' 'Owner verifies complete input and speech logs' 'Speech/SQLite/log chua PASS nen khong du bang chung MAN-06' 'BLOCKED'
    }
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
      Prompt-Owner 'MAN-07' 'SAU khi script dung PR95: anh da test keyboard hoat dong lai va Steam, Diablo IV, NVDA van dang chay?'
      # GO/NO-GO is an explicit OWNER decision only AFTER all DF rounds.
      # This runner intentionally leaves DF-02/10/11 and physical-origin
      # approval pending; never solicit a premature one-key Y sign-off.
      Set-Result 'MAN-08' 'Owner separately approves V1 GO/NO-GO after all DF evidence' 'BLOCKED: chi xin GO/NO-GO sau khi DF-02, DF-10, DF-11 va physical review hoan tat' 'BLOCKED'
      Write-Host 'MAN-08 la quyet dinh duyet RIENG sau khi tat ca test du bang chung; hien giu BLOCKED.'
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
# Fail closed: preflight and UAT errors must not return a false-success exit.
# A complete physical/owner acceptance requires the submitted JSON evidence,
# not simply exit code zero from a script.
if($failures.Count -gt 0){exit 2}
if($Mode -eq 'Review' -and @($items.Values | Where-Object { $_.result -ne 'PASS' }).Count -gt 0){
  # Review intentionally leaves DF-11/DF-14 or unanswered owner checkpoints
  # BLOCKED; a generated report is NOT equivalent to final acceptance PASS.
  exit 3
}
exit 0
