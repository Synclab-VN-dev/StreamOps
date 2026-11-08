param(
  [Parameter(Mandatory=$true)][string]$OldSetup,
  [Parameter(Mandatory=$true)][string]$Setup,
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$Sandbox
)
# Run directly from PowerShell on an isolated VM, not below a Python test runner:
# production migration deliberately refuses other Python writers. No production
# registration is modified. Only the unused UAT identity and a new sandbox.
$ErrorActionPreference='Stop'
$keys=@('HKCU:\Software\Synclab\D4Planner-UAT','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4PlannerUAT')
foreach($key in $keys){if(Test-Path $key){throw 'Existing UAT identity belongs to another run'}}
if(Test-Path -LiteralPath $Sandbox){throw 'New sandbox required'}
New-Item -ItemType Directory -Path $Sandbox | Out-Null
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $Sandbox /inheritance:r /grant:r "*$($sid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Sandbox ACL failed'}
$root=Join-Path $Sandbox 'application'
$local=Join-Path $Sandbox 'local'
$legacy=Join-Path $local 'd4planner'
$data=Join-Path $local 'StreamOps\D4Planner'
$savedEnv=@{}
foreach($name in @('LOCALAPPDATA','TEMP','TMP','D4PLANNER_LAUNCH_REPORT')){$savedEnv[$name]=[Environment]::GetEnvironmentVariable($name)}
foreach($name in @('D4PLANNER_DATA_ROOT','D4PLANNER_HOME','D4PLANNER_STORAGE_ISOLATED','D4PLANNER_DATA_DIR','D4_RULEKIT_DATA_ROOT')){
  if([Environment]::GetEnvironmentVariable($name)){throw "Conflicting inherited environment: $name"}
}
$production=@('HKCU:\Software\Synclab\D4Planner','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4Planner')
function ProductionState {
  $values=@{}
  foreach($key in $production){if(Test-Path $key){$values[$key]=Get-ItemProperty $key|Select-Object InstallRoot,DataRoot,DisplayVersion,InstallLocation,UninstallString}else{$values[$key]=$null}}
  return ($values|ConvertTo-Json -Depth 5 -Compress)
}
$productionBefore=ProductionState
$report=@{status='RUNNING';cases=@();oldSetupSha256=(Get-FileHash $OldSetup).Hash;setupSha256=(Get-FileHash $Setup).Hash;sessionId=(Get-Process -Id $PID).SessionId;limits=@('Headless Win32 dialog automation; Owner visual MAN not executed')}
$owned=@()
$env:LOCALAPPDATA=$local
$env:TEMP=Join-Path $Sandbox 'temp';$env:TMP=$env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force|Out-Null
Add-Type @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class Setup184UI {
  public delegate bool Visitor(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] static extern bool EnumWindows(Visitor v,IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
  [DllImport("user32.dll")] static extern IntPtr GetDlgItem(IntPtr h,int id);
  [DllImport("user32.dll")] static extern bool IsWindowEnabled(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h,int command);
  [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
  public static IntPtr[] Windows(uint pid) {var hs=new List<IntPtr>();EnumWindows((h,p)=>{uint owner;GetWindowThreadProcessId(h,out owner);if(owner==pid)hs.Add(h);return true;},IntPtr.Zero);return hs.ToArray();}
  public static string Title(IntPtr h){var s=new StringBuilder(512);GetWindowText(h,s,s.Capacity);return s.ToString();}
  public static string Describe(IntPtr h){var b=GetDlgItem(h,1);return h+" title="+Title(h)+" next="+b+" visible="+IsWindowVisible(b)+" enabled="+IsWindowEnabled(b);}
  // Session 0 has no visible desktop. Drive real enabled controls on this run's
  // PID-filtered dialogs, as with the migration MessageBox test. This verifies
  // the functional flow, not visual accessibility or an interactive desktop.
  public static bool Click(IntPtr h,int id){ShowWindow(h,5);var b=GetDlgItem(h,id);return b!=IntPtr.Zero && IsWindowEnabled(b) && PostMessage(b,0xF5,IntPtr.Zero,IntPtr.Zero);}
}
'@
function LaunchOwned([string]$File,[string[]]$Arguments) {
  if($Arguments.Count -and $Arguments[0]){$p=Start-Process -FilePath $File -ArgumentList $Arguments -PassThru}
  else{$p=Start-Process -FilePath $File -PassThru}
  [void]$p.Handle
  $script:owned+=,$p
  return $p
}
function WaitExit($p,[int]$Seconds=240) {
  if(-not $p.WaitForExit($Seconds*1000)){throw 'Owned process timeout'}
  $p.Refresh()
  return $p.ExitCode
}
function SetupArgs([bool]$Silent) {
  $a=@('/ISOLATED=1',('/DATADIR="'+$data+'"'),('/INSTALLROOT="'+$root+'"'))
  if($Silent){$a=@('/S')+$a}
  return $a
}
function HashFixtures([string]$Base) {
  $hashes=@{}
  foreach($name in @('state\fixture.sqlite3','targets\preserve.bin','rulekit\preserve.bin')){$hashes[$name]=(Get-FileHash -LiteralPath (Join-Path $Base $name)).Hash}
  return $hashes
}
function Preserved($Expected,[string]$Base) {
  $actual=HashFixtures $Base
  foreach($key in $Expected.Keys){if($actual[$key] -ne $Expected[$key]){throw "Fixture changed: $key"}}
}
function PythonCode([string]$Code,[string]$DbPath) {
  $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Code))
  & $Python -I -B -c "import base64;exec(base64.b64decode('$encoded'))" $DbPath
  if($LASTEXITCODE -ne 0){throw 'Fixture Python command failed'}
}
try {
  New-Item -ItemType Directory -Path (Join-Path $legacy 'state'),(Join-Path $legacy 'targets'),(Join-Path $legacy 'rulekit') -Force|Out-Null
  $db=Join-Path $legacy 'state\fixture.sqlite3'
  PythonCode 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("CREATE TABLE equipment(revision INTEGER)"); c.execute("INSERT INTO equipment VALUES(42)"); c.commit(); c.close()' $db
  [IO.File]::WriteAllText((Join-Path $legacy 'targets\preserve.bin'),'preserve')
  [IO.File]::WriteAllText((Join-Path $legacy 'rulekit\preserve.bin'),'preserve')
  $report.before=HashFixtures $legacy
  $old=LaunchOwned $OldSetup (SetupArgs $true)
  if((WaitExit $old) -ne 0){throw 'Old Setup failed to install baseline'}
  $env:D4PLANNER_LAUNCH_REPORT=Join-Path $Sandbox 'launch-before.json'
  $launcher=LaunchOwned (Join-Path $root 'D4Planner.exe') @('')
  $deadline=(Get-Date).AddSeconds(30)
  while((Get-Date) -lt $deadline -and -not $launcher.HasExited){
    if((Test-Path $env:D4PLANNER_LAUNCH_REPORT) -and @([Setup184UI]::Windows($launcher.Id)).Count){break}
    Start-Sleep -Milliseconds 100
  }
  $launch=Get-Content $env:D4PLANNER_LAUNCH_REPORT -Raw|ConvertFrom-Json
  if($launch.error -notlike '*MIGRATION_REQUIRED*' -or $launcher.HasExited){throw 'Legacy error was not reproduced'}
  $report.beforePid=$launcher.Id
  $report.beforeLaunchError=$launch.error
  $report.beforeDialogHandles=@([Setup184UI]::Windows($launcher.Id)|ForEach-Object {$_.ToInt64()})
  if(-not $report.beforeDialogHandles.Count){throw 'Legacy dialog missing'}
  $retry=LaunchOwned $OldSetup (SetupArgs $true)
  $retryExit=WaitExit $retry
  $failure=Get-ChildItem $env:TEMP -Filter 'D4Planner-setup-*.json'|Sort-Object LastWriteTimeUtc -Descending|Select-Object -First 1
  $failureBody=Get-Content $failure.FullName -Raw|ConvertFrom-Json
  if($retryExit -eq 0 -or $failureBody.error -notlike '*WinError 5*'){throw 'Old Setup did not reproduce WinError 5'}
  $report.cases+=@{id='old-setup-launch-reinstall';status='EXPECTED_FAIL';exit=$retryExit;error=$failureBody.error}
  Preserved $report.before $legacy
  $next=LaunchOwned $Setup (SetupArgs $false)
  $deadline=(Get-Date).AddMinutes(8);$confirmations=@{};$iteration=0
  while(-not $next.HasExited -and (Get-Date) -lt $deadline) {
    if(($iteration % 10) -eq 0){
      @{pid=$next.Id;windows=@([Setup184UI]::Windows($next.Id)|ForEach-Object {[Setup184UI]::Describe($_)})}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $Sandbox 'wizard-progress.json')
    }
    $iteration++
    foreach($hwnd in [Setup184UI]::Windows($next.Id)){[void][Setup184UI]::Click($hwnd,1)}
    $all=@(Get-CimInstance Win32_Process)
    $ids=@([uint32]$next.Id)
    do{$added=@($all|Where-Object {$_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids}|ForEach-Object {$_.ProcessId});$ids+=$added}while($added.Count)
    foreach($childId in $ids){foreach($hwnd in [Setup184UI]::Windows($childId)){
      $title=[Setup184UI]::Title($hwnd)
      if($title -eq 'D4Planner Setup - Transfer legacy data'){
        $confirmations[$hwnd.ToInt64()]=[uint32]$childId
        [void][Setup184UI]::Click($hwnd,6)
      }elseif($title -eq 'D4Planner Setup' -and $childId -ne $next.Id){
        [void][Setup184UI]::Click($hwnd,1)
        throw 'Setup engine reported failure; inspect private installer report'
      }
    }}
    Start-Sleep -Milliseconds 150
    $next.Refresh()
  }
  if((WaitExit $next 5) -ne 0){throw 'New Setup failed'}
  if($confirmations.Count -ne 1){throw 'Expected exactly one migration confirmation'}
  if(-not $launcher.HasExited){throw 'New Setup left old launcher alive'}
  $report.confirmationCount=$confirmations.Count
  Preserved $report.before $legacy
  Preserved $report.before $data
  $active=Get-Content (Join-Path $root 'active.json') -Raw|ConvertFrom-Json
  $manifest=Get-Content (Join-Path (Join-Path $root $active.payload) 'release-manifest.json') -Raw|ConvertFrom-Json
  $report.sourceHead=$manifest.sourceHead
  $report.cases+=@{id='interactive-setup-confirmed-migration';status='PASS'}
  $env:D4PLANNER_LAUNCH_REPORT=Join-Path $Sandbox 'launch-after.json'
  $viewer=LaunchOwned (Join-Path $root 'D4Planner.exe') @('--viewer')
  $deadline=(Get-Date).AddSeconds(45)
  do {
    $tree=@(Get-CimInstance Win32_Process|Where-Object {$_.ParentProcessId -eq $viewer.Id}|Select-Object ProcessId,Name)
    if($viewer.HasExited -or ($tree|Where-Object {$_.Name -eq 'd4planner-fe.exe'})){break}
    Start-Sleep -Milliseconds 200
  } while((Get-Date) -lt $deadline)
  $report.viewerExited=$viewer.HasExited
  if(Test-Path $env:D4PLANNER_LAUNCH_REPORT){$report.viewerLaunchReport=Get-Content $env:D4PLANNER_LAUNCH_REPORT -Raw|ConvertFrom-Json}
  if($viewer.HasExited -or -not($tree|Where-Object {$_.Name -eq 'd4planner-fe.exe'})){throw 'Post-migration viewer failed'}
  $report.viewerTree=$tree
  $reinstall=LaunchOwned $Setup (SetupArgs $true)
  if((WaitExit $reinstall) -ne 0 -or -not $viewer.HasExited){throw 'Reinstall did not stop real running viewer'}
  $report.cases+=@{id='launch-and-same-version-reinstall';status='PASS'}
  Preserved $report.before $data
  Preserved $report.before $legacy
  $report.after=HashFixtures $data
  PythonCode 'import sqlite3,sys,json; from pathlib import Path; c=sqlite3.connect(Path(sys.argv[1]).as_uri()+"?mode=ro",uri=True); print(json.dumps({"integrity":c.execute("PRAGMA integrity_check").fetchone()[0],"revision":c.execute("SELECT revision FROM equipment").fetchone()[0]}));c.close()' (Join-Path $data 'state\fixture.sqlite3') | Set-Content (Join-Path $Sandbox 'sqlite.json')
  $report.sqlite=Get-Content (Join-Path $Sandbox 'sqlite.json') -Raw|ConvertFrom-Json
  if($report.sqlite.integrity -ne 'ok' -or $report.sqlite.revision -ne 42){throw 'SQLite data changed'}
  $report.status='PASS'
} catch {
  $report.status='FAIL';$report.error=$_.Exception.Message
} finally {
  foreach($p in $owned){if(-not $p.HasExited){$p.Kill();[void]$p.WaitForExit(10000)}}
  try {
    $uninstaller=Join-Path $root 'Uninstall.exe'
    if(Test-Path $uninstaller){$p=Start-Process $uninstaller -ArgumentList '/S' -PassThru;if(-not $p.WaitForExit(90000)){throw 'Uninstall timeout'}
      $deadline=(Get-Date).AddSeconds(90);while((Test-Path $uninstaller) -and (Get-Date) -lt $deadline){Start-Sleep -Milliseconds 200}
      if(Test-Path $uninstaller){throw 'Uninstall incomplete'}
    }
    foreach($key in $keys){if(Test-Path $key){throw 'UAT registration not cleaned'}}
    if((ProductionState) -ne $productionBefore){throw 'Production registration changed'}
    if($report.before){Preserved $report.before $legacy}
    $report.ownedCleanup=$true
  } catch {$report.status='FAIL';$report.cleanupError=$_.Exception.Message}
  foreach($name in $savedEnv.Keys){[Environment]::SetEnvironmentVariable($name,$savedEnv[$name])}
  $report|ConvertTo-Json -Depth 12|Set-Content -LiteralPath (Join-Path $Sandbox 'report.json') -Encoding UTF8
}
$report|ConvertTo-Json -Depth 12
if($report.status -eq 'PASS'){exit 0}else{exit 1}
