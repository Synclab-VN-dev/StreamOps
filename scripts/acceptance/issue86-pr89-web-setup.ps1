#requires -Version 7.0
# #86/#89 isolated Windows A WEB UAT; does not operate Steam/D4/OBS lifecycle.
[CmdletBinding()]
param(
    [ValidateSet("SelfTest","Setup")][string]$Mode="Setup",
    [string]$RepoRoot="C:\Workspace\StreamOps",
    [string]$WorktreeRoot="C:\Workspace\StreamOps-PR89-UAT",
    [string]$ExpectedHead="",
    [string]$OutputRoot=""
)
Set-StrictMode -Version Latest
$ErrorActionPreference="Stop"
$Port=18789
$TaskName="StreamOps-PR89-Manual"
$Ref="refs/heads/feat/86-game-manager-ws-ui"
if(-not $OutputRoot){$OutputRoot=Join-Path ([IO.Path]::GetTempPath()) "StreamOps-I86-Web-Setup"}
$RunRoot=Join-Path $OutputRoot ((Get-Date -Format "yyyyMMdd-HHmmss-fff")+"-pr89")
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$Cases=[System.Collections.Generic.List[object]]::new()
$Done=$false
$Log=Join-Path $RunRoot "setup.log"
function Record([string]$case,[string]$status,[string]$expected,[string]$actual,[string]$details){
    if($status -notin @("PASS","FAIL","BLOCKED")){throw "Invalid status: $status"}
    $Cases.Add([pscustomobject]@{id=$case;status=$status;expected=$expected;actual=$actual;details=$details})
    $msg="$case [$status] $details"
    Add-Content -LiteralPath $Log -Encoding UTF8 -Value $msg
    Write-Host $msg
}
function Block([string]$case,[string]$expected,[string]$actual,[string]$details){
    Record $case "BLOCKED" $expected $actual $details
    throw "BLOCKED: $case — $details"
}
function Assert-NoOccupiedPort([object[]]$listeners){
    if($listeners.Count -gt 0){
        throw "Port 18789 occupied by PID(s): $(($listeners | ForEach-Object OwningProcess | Select-Object -Unique) -join ','). Do not stop or reuse."
    }
}
function Assert-Environment {
    if($env:OS -ne "Windows_NT"){Block "OS" "Windows A" "$env:OS" "Setup is Windows-only"}
    if(-not (Get-Command git -ErrorAction SilentlyContinue)){
        Block "GIT" "Git on PATH" "Absent" "Git must be present on A"
    }
    if(-not (Test-Path -LiteralPath $RepoRoot -PathType Container) -or
       -not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))){
        Block "BASE-REPO" "Existing StreamOps Git checkout" $RepoRoot "No valid base repo; never modify an unrelated folder"
    }
    $origin=(& git -C $RepoRoot remote get-url origin 2>&1 | Out-String).Trim()
    if($LASTEXITCODE -ne 0 -or $origin -notmatch "(?i)Synclab-VN-dev[/\\]StreamOps(?:\.git)?$"){
        Block "ORIGIN" "Synclab-VN-dev/StreamOps origin" $origin "Wrong source repo"
    }
    Record "BASE-REPO" "PASS" "Original repository untouched" $RepoRoot "Origin verified: $origin"
    $listener=@(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    try{Assert-NoOccupiedPort $listener}
    catch{Block "PORT" "18789 unoccupied" "Listener(s) present" $_.Exception.Message}
    Record "PORT" "PASS" "18789 not listening" "Free" "No existing service replaced"
    $task=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if($null -ne $task){Block "TASK" "No existing $TaskName" "$($task.State)" "Protect existing Scheduled Task; no forced registration"}
    Record "TASK" "PASS" "No existing PR89 Scheduled Task" "Absent" "Safe to prepare a new isolated task"
    if(-not (Get-CimInstance Win32_ComputerSystem).UserName){
        Block "SESSION" "Interactive Windows desktop user" "None" "Log in to Windows session before setup"
    }
    Record "SESSION" "PASS" "Interactive console" "Present" "Node start uses logged-in desktop"
}
function Choose-Python {
    if(Get-Command py -ErrorAction SilentlyContinue){
        & py -3.12 -c 'import sys; assert sys.version_info >= (3,12)'
        if($LASTEXITCODE -eq 0){return @("py","-3.12")}
    }
    $python=Get-Command python -ErrorAction SilentlyContinue
    if($python){
        & $python.Source -c 'import sys; assert sys.version_info >= (3,12)'
        if($LASTEXITCODE -eq 0){return @($python.Source)}
    }
    throw "Python >= 3.12 not installed or not on PATH; no system interpreter changes made"
}
try {
    if($Mode -eq "SelfTest"){
        Assert-NoOccupiedPort @()
        $blocked=$false
        try{Assert-NoOccupiedPort @([pscustomobject]@{OwningProcess=99999})}catch{$blocked=$true}
        if(-not $blocked){throw "Occupied port erroneously accepted"}
        if($Port -ne 18789 -or $TaskName -ne "StreamOps-PR89-Manual"){throw "Isolation contract mismatch"}
        Record "SELFTEST" "PASS" "Port collision blocks; static scope correct" "Synthetic checks passed" "No Git, task, port or game mutation performed"
        $Done=$true
    }else{
        if($ExpectedHead -notmatch '^[a-fA-F0-9]{40}$'){
            Block "HEAD" "Full 40-character approved PR89 HEAD" "$ExpectedHead" "Pass -ExpectedHead with SHA from PR #89"
        }
        $ExpectedHead=$ExpectedHead.ToLowerInvariant()
        $RepoRoot=[IO.Path]::GetFullPath($RepoRoot)
        $WorktreeRoot=[IO.Path]::GetFullPath($WorktreeRoot)
        if($WorktreeRoot -eq $RepoRoot -or
           $WorktreeRoot.StartsWith($RepoRoot.TrimEnd('\')+'\', [StringComparison]::OrdinalIgnoreCase)){
            Block "WORKTREE" "Standalone sibling worktree" $WorktreeRoot "Never install test environment inside active base checkout"
        }
        Assert-Environment
        & git -C $RepoRoot fetch --no-tags origin $Ref
        if($LASTEXITCODE -ne 0){Block "FETCH" "$Ref reachable" "Fetch failed" "Git credentials/connectivity; original branch untouched"}
        $remoteHead=(& git -C $RepoRoot rev-parse FETCH_HEAD 2>&1 | Out-String).Trim().ToLowerInvariant()
        if($remoteHead -ne $ExpectedHead){
            Block "HEAD" "$ExpectedHead" "$remoteHead" "Remote PR branch advanced. Use the currently verified PR SHA; no stale checkout."
        }
        Record "HEAD" "PASS" $ExpectedHead $remoteHead "Remote branch pinned to exact commit"
        if(Test-Path -LiteralPath $WorktreeRoot){
            if(-not (Test-Path -LiteralPath (Join-Path $WorktreeRoot ".git"))){
                Block "WORKTREE" "Existing valid isolated checkout" $WorktreeRoot "Target exists but is not Git worktree; will not overwrite"
            }
            $actual=(& git -C $WorktreeRoot rev-parse HEAD 2>&1 | Out-String).Trim()
            if($LASTEXITCODE -ne 0 -or $actual -ne $ExpectedHead){
                Block "WORKTREE" $ExpectedHead $actual "Existing worktree at wrong commit; will not reset"
            }
            Record "WORKTREE" "PASS" $ExpectedHead $actual "Reusing existing exact checkout without reset"
        }else{
            & git -C $RepoRoot worktree add --detach $WorktreeRoot $ExpectedHead
            if($LASTEXITCODE -ne 0){Block "WORKTREE" "Isolated Git worktree" "Creation failed" "Base checkout remains untouched"}
            Record "WORKTREE" "PASS" $ExpectedHead $WorktreeRoot "Added detached worktree at pinned HEAD"
        }
        $venv=Join-Path $WorktreeRoot ".venv"
        $venvPython=Join-Path $venv "Scripts\python.exe"
        if(-not (Test-Path -LiteralPath $venvPython -PathType Leaf)){
            $pyArgs=@(Choose-Python)
            & $pyArgs[0] @($pyArgs | Select-Object -Skip 1) -m venv $venv
            if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)){
                Block "VENV" "Isolated Python environment" "Creation failed" "No system runtime modified"
            }
        }
        Record "VENV" "PASS" "Local PR89 Python" $venvPython "Independent Python environment"
        & $venvPython -m pip install --disable-pip-version-check --no-input -e "$WorktreeRoot[server]"
        if($LASTEXITCODE -ne 0){Block "INSTALL" "StreamOps [server] dependencies inside isolated venv" "pip failed" "Inspect pip output; system Python remains untouched"}
        & $venvPython -c 'import fastapi,uvicorn,streamops.server.app'
        if($LASTEXITCODE -ne 0){Block "IMPORT" "FastAPI + StreamOps importable" "Import failure" "Do not start UAT task"}
        Record "INSTALL" "PASS" "Isolated server package" $venv "No global Python dependency changes"
        $data=Join-Path $WorktreeRoot ".streamops\pr89\node"
        New-Item -ItemType Directory -Force -Path $data | Out-Null
        # Prevent a port/task collision introduced between initial preflight and start.
        try{Assert-NoOccupiedPort @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)}
        catch{Block "PORT-RECHECK" "Port 18789 still unoccupied" "Occupied" $_.Exception.Message}
        if(Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue){
            Block "TASK-RECHECK" "No conflicting task" "Task exists" "No overwriting existing Scheduled Task"
        }
        $start=Join-Path $WorktreeRoot "scripts\devices\a-windows\start-streamops-node.ps1"
        if(-not (Test-Path -LiteralPath $start -PathType Leaf)){
            Block "LAUNCHER" "Repository-managed interactive launcher" "Missing" "Cannot start safely"
        }
        & $start -TaskName $TaskName -Port $Port -BindHost "0.0.0.0" -DataDir $data -PythonPath $venvPython
        $page1=Invoke-WebRequest -Uri "http://127.0.0.1:$Port/steam" -TimeoutSec 6 -UseBasicParsing
        $page2=Invoke-WebRequest -Uri "http://127.0.0.1:$Port/games" -TimeoutSec 6 -UseBasicParsing
        if($page1.StatusCode -ne 200 -or $page2.StatusCode -ne 200){
            Block "WEB" "Both routes return 200" "$($page1.StatusCode)/$($page2.StatusCode)" "Do not infer UI pass"
        }
        Record "WEB" "PASS" "/steam and /games return HTTP 200" "200/200" "Browser-level UI behavior must still be reviewed on A/B"
        $ipv4=@(Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
            Select-Object -ExpandProperty IPAddress)
        Write-Host "LOCAL: http://localhost:$Port/steam   http://localhost:$Port/games"
        foreach($ip in $ipv4){Write-Host "LAN: http://$($ip):$Port/steam   http://$($ip):$Port/games"}
        Write-Host "Only on a trusted LAN. Do NOT expose this unauthenticated test endpoint to the internet."
        $Done=$true
    }
}catch{
    if(-not (@($Cases | Where-Object status -eq "BLOCKED").Count)){
        Record "SETUP" "BLOCKED" "Safe isolated web environment" "Incomplete" $_.Exception.Message
    }
}finally{
    $result=[ordered]@{
        ticket=86;pr=89;mode=$Mode;head=$ExpectedHead;worktree=$WorktreeRoot
        port=$Port;task=$TaskName;data_dir=(Join-Path $WorktreeRoot ".streamops\pr89\node")
        status=$(if($Done){"PASS"}else{"BLOCKED"})
        cases=@($Cases.ToArray());host=$env:COMPUTERNAME;time=(Get-Date).ToString("o")
        no_steam_obs_or_game_lifecycle_calls=$true
    }
    $json=Join-Path $RunRoot "report.json"
    $result | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $json -Encoding UTF8
    Write-Host "REPORT: $json"
    Write-Host "ISSUE86_PR89_WEB_SETUP=$($result.status)"
}
if(-not $Done){exit 2}
exit 0
