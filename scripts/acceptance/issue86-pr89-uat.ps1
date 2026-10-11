#requires -Version 7.0
# Ticket #86 / PR #89. Read-only, fail-closed A/B acceptance collector.
# Does NOT install software, register/start/stop tasks, restart Steam, mutate games,
# disable OBS, cut networking, or make localhost lifecycle requests.
[CmdletBinding()]
param(
    [ValidateSet("SelfTest", "Preflight", "ReadOnly")]
    [string]$Mode = "Preflight",
    [string]$ExpectedHead = "",
    [string]$WorktreeRoot = "",
    [string]$OutputRoot = "",
    [ValidateRange(1, 30)][int]$WsTimeoutSeconds = 6
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ExpectedPort = 18789
$ExpectedTask = "StreamOps-PR89-Manual"
# Supports a separately downloaded CI artifact script while still validating
# the exact local PR #89 worktree before contacting any listener.
$RepoRoot = if ($WorktreeRoot) {
    [IO.Path]::GetFullPath($WorktreeRoot)
} else {
    [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
}
$ExpectedDataDir = [IO.Path]::GetFullPath((Join-Path $RepoRoot ".streamops/pr89/node"))
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path ([IO.Path]::GetTempPath()) "StreamOps-I86-UAT"
}
$RunId = (Get-Date -Format "yyyyMMdd-HHmmss-fff") + "-pr89"
$EvidenceDir = Join-Path $OutputRoot $RunId
New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
$Results = [System.Collections.Generic.List[object]]::new()
$Metadata = [ordered]@{
    ticket=86; pr=89; mode=$Mode; readonly=$true; port=$ExpectedPort
    task=$ExpectedTask; data_dir=$ExpectedDataDir
    repo_root=$RepoRoot; expected_head=$ExpectedHead; observed_head=$null
    created_at=(Get-Date).ToString("o")
    host=$env:COMPUTERNAME; ps_version=$PSVersionTable.PSVersion.ToString()
}
$LogPath = Join-Path $EvidenceDir "runner.log"
function Write-Audit([string]$message) {
    $line = (Get-Date).ToString("o") + " " + $message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    Write-Host $message
}
function Add-Case([string]$id,[string]$status,[string]$category,[string]$expected,[string]$actual,[string]$detail) {
    if ($status -notin @("PASS","FAIL","BLOCKED","SKIP")) { throw "Invalid case status: $status" }
    if ($category -notin @("harness","environment","product","owner","evidence")) { throw "Invalid category: $category" }
    $Results.Add([pscustomobject]@{
        id=$id; status=$status; category=$category
        expected=$expected; actual=$actual; detail=$detail
    })
    Write-Audit "$id [$status/$category] $detail"
}
function Save-Report {
    $counts=[ordered]@{}
    foreach($name in @("PASS","FAIL","BLOCKED","SKIP")) {
        $counts[$name]=@($Results | Where-Object status -eq $name).Count
    }
    $report=[ordered]@{
        schema_version=1; metadata=$Metadata; summary=$counts
        outcome=$(if($counts.FAIL -gt 0){"FAIL"}elseif($counts.BLOCKED -gt 0){"BLOCKED"}else{"PASS"})
        cases=@($Results.ToArray())
        evidence=@("runner.log","report.json","summary.txt")
        lifecycle_actions_performed=0
    }
    $reportFile=Join-Path $EvidenceDir "report.json"
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportFile -Encoding UTF8
    @(
        "ISSUE86_PR89_UAT=$($report.outcome) PASS=$($counts.PASS) FAIL=$($counts.FAIL) BLOCKED=$($counts.BLOCKED) SKIP=$($counts.SKIP)"
        "HEAD=$($Metadata.observed_head) MODE=$Mode"
        "PORT=$ExpectedPort TASK=$ExpectedTask"
        "No lifecycle/game/OBS mutations performed."
        "Evidence: $reportFile"
    ) | Set-Content -LiteralPath (Join-Path $EvidenceDir "summary.txt") -Encoding UTF8
    Write-Host "Evidence: $reportFile"
    Write-Host "ISSUE86_PR89_UAT=$($report.outcome) PASS=$($counts.PASS) FAIL=$($counts.FAIL) BLOCKED=$($counts.BLOCKED) SKIP=$($counts.SKIP)"
    if($counts.FAIL -gt 0){return 1}
    if($counts.BLOCKED -gt 0){return 2}
    return 0
}
function Add-OwnerCases {
    foreach($id in @("DEVF-02","DEVF-03","DEVF-04","DEVF-05","DEVF-06",
                     "MAN-01","MAN-02","MAN-03","MAN-04","MAN-05")) {
        $reason=switch($id) {
            "DEVF-02" {"A real external game state transition and two UI consumers on A/B are required; passive WS connection is not push evidence"}
            "DEVF-03" {"Network interruption, wrong Windows session, OBS black/configured-only and actual recovery require separately authorized real-environment testing"}
            "DEVF-04" {"Real Android B navigation and screenshot/Golden review require device evidence"}
            "DEVF-05" {"Real Steam/Diablo IV Start/Stop/Restart requires explicit owner-approved test window; never run in this script"}
            "DEVF-06" {"Must collect complete DEVF-01..05 evidence on actual A/B; CI PASS is not real-host acceptance"}
            default {"Owner must visually/manual-review actual A/B evidence; no synthetic PASS"}
        }
        Add-Case $id "BLOCKED" "owner" "Real A/B evidence and explicit approval as applicable" "Not executed" $reason
    }
}
function Test-PortOwnership([object[]]$listeners, $runtime, [int]$port) {
    if($null -eq $runtime -or $listeners.Count -lt 1){return $false}
    if([int]$runtime.port -ne $port -or [int]$runtime.pid -le 0){return $false}
    $owners=@($listeners | ForEach-Object { [int]$_.OwningProcess } | Select-Object -Unique)
    return ($owners.Count -eq 1 -and $owners[0] -eq [int]$runtime.pid)
}
function Invoke-SelfTest {
    $synthetic = @(
        [pscustomobject]@{id="PASS";status="PASS";category="environment"},
        [pscustomobject]@{id="FAIL";status="FAIL";category="product"},
        [pscustomobject]@{id="BLOCKED";status="BLOCKED";category="owner"},
        [pscustomobject]@{id="SKIP";status="SKIP";category="evidence"}
    )
    foreach ($status in @("PASS","FAIL","BLOCKED","SKIP")) {
        if (@($synthetic | Where-Object status -eq $status).Count -ne 1) {
            throw "Status classifier does not preserve $status"
        }
    }
    $serialized = $synthetic | ConvertTo-Json -Depth 4 | ConvertFrom-Json
    if(@($serialized).Count -ne 4){throw "JSON report round-trip failed"}
    $source=Get-Content -LiteralPath $PSCommandPath -Raw
    foreach ($forbidden in @("Stop-ScheduledTask ", "Stop-Process ", "Register-ScheduledTask ",
        "Start-ScheduledTask ", "Start-Process ", "Invoke-Expression ", "Invoke-RestMethod -Method Post")) {
        # Exclude the safety denylist declaration itself, inspect operative lines only.
        $executableLines=@($source -split "\r?\n" | Where-Object {
            $_ -notmatch '^\s*#' -and $_ -notmatch '^\s*foreach \(\$forbidden' -and
            $_ -notmatch '^\s*\$source=' -and $_ -notmatch '^\s*if \(\$executableLines'
        })
        $matches=@($executableLines | Where-Object {
            $_.Contains($forbidden) -and $_ -notmatch '^\s*foreach \(' -and
            $_ -notmatch '^\s*"'
        })
        if ($matches.Count) { throw "Forbidden mutating command appears executable: $forbidden" }
    }
    $good=@([pscustomobject]@{OwningProcess=8186},[pscustomobject]@{OwningProcess=8186})
    $foreign=@([pscustomobject]@{OwningProcess=8186},[pscustomobject]@{OwningProcess=9011})
    $runtime=[pscustomobject]@{pid=8186;port=18789}
    if(-not (Test-PortOwnership $good $runtime 18789)){throw "Same-PID dual-stack port guard rejected"}
    if(Test-PortOwnership $foreign $runtime 18789){throw "Foreign PID port collision was accepted"}
    if(Test-PortOwnership $good $null 18789){throw "Missing runtime was accepted"}
    if(Test-PortOwnership @() $runtime 18789){throw "Missing listener was accepted"}
    $missing=Join-Path ([IO.Path]::GetTempPath()) ("issue86-missing-"+[Guid]::NewGuid().ToString("N"))
    if((Get-WorktreePathIssue $missing) -notlike "Directory does not exist:*") {
        throw "Missing worktree classification regression"
    }
    $notRepo=Join-Path ([IO.Path]::GetTempPath()) ("issue86-notrepo-"+[Guid]::NewGuid().ToString("N"))
    try {
        New-Item -Path $notRepo -ItemType Directory -Force | Out-Null
        if((Get-WorktreePathIssue $notRepo) -notlike "*not a Git checkout/worktree root*") {
            throw "Non-Git directory classification regression"
        }
    } finally {
        Remove-Item -LiteralPath $notRepo -Recurse -Force -ErrorAction SilentlyContinue
    }
    Add-Case "RUNNER-SELFTEST" "PASS" "harness" "Status classification, JSON, safe port owner identity, no-mutation audit" "Synthetic PASS/FAIL/BLOCKED/SKIP + collision tests passed" "No Windows A processes, listeners or WS endpoints accessed"
}
function Get-WorktreePathIssue([string]$path) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        return "Directory does not exist: $path"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $path ".git"))) {
        return "Directory exists but is not a Git checkout/worktree root: $path"
    }
    return ""
}
function Find-IsolatedPR89Worktrees {
    # Shallow, bounded, read-only discovery. Never scan complete volumes.
    $parents = @()
    if ($env:SystemDrive) { $parents += (Join-Path $env:SystemDrive "Workspace") }
    if ($HOME) { $parents += (Join-Path $HOME "codex-work") }
    $found = [System.Collections.Generic.List[object]]::new()
    foreach ($parent in ($parents | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) { continue }
        $children = @(Get-ChildItem -LiteralPath $parent -Directory -ErrorAction SilentlyContinue |
            Select-Object -First 80)
        foreach ($candidate in $children) {
            if (-not (Test-Path -LiteralPath (Join-Path $candidate.FullName ".git"))) { continue }
            try {
                $gitBranch=(& git -C $candidate.FullName branch --show-current 2>$null | Out-String).Trim()
                $gitHead=(& git -C $candidate.FullName rev-parse HEAD 2>$null | Out-String).Trim()
                if ($LASTEXITCODE -ne 0 -or $gitHead -notmatch '^[0-9a-f]{40}
    $safe = $true
    try {
        $branch = (& git -C $RepoRoot branch --show-current 2>&1 | Out-String).Trim()
        $head = (& git -C $RepoRoot rev-parse HEAD 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {throw "git HEAD unavailable"}
        $Metadata.observed_head=$head
        if ($branch -ne "feat/86-game-manager-ws-ui" -or
            ($ExpectedHead -and $head -ne $ExpectedHead)) {
            Add-Case "PRE-HEAD" "BLOCKED" "environment" "PR #89 branch and expected HEAD" "$branch $head" "Checkout exact PR #89 worktree; do not run from master/default"
            $safe=$false
        } else {
            Add-Case "PRE-HEAD" "PASS" "environment" "PR #89 worktree and pinned head" "$branch $head" "Branch identity verified"
        }
    } catch {
        Add-Case "PRE-HEAD" "BLOCKED" "environment" "Git and PR #89 worktree" "Unavailable" "git preflight: $($_.Exception.Message)"
        $safe=$false
    }
    if ($env:OS -ne "Windows_NT") {
        Add-Case "PRE-OS" "BLOCKED" "environment" "Windows A, PowerShell 7" "$($env:OS)" "UAT on A requires Windows; CI SelfTest only is allowed elsewhere"
        return $false
    }
    Add-Case "PRE-OS" "PASS" "environment" "Windows A, PowerShell 7" "Windows_NT" "Read-only Windows API preflight"
    try {
        if (-not (Test-Path -LiteralPath $ExpectedDataDir -PathType Container)) {
            Add-Case "PRE-DATADIR" "BLOCKED" "environment" "Existing isolated $ExpectedDataDir" "Missing" "No directory created by this UAT runner"
            $safe=$false
        } else {
            Add-Case "PRE-DATADIR" "PASS" "environment" "Isolated PR89 DataDir" $ExpectedDataDir "DataDir present"
        }
        $task=Get-ScheduledTask -TaskName $ExpectedTask -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            Add-Case "PRE-TASK" "BLOCKED" "environment" "Existing task $ExpectedTask" "Missing" "Runner never registers/starts tasks"
            $safe=$false
        } else {
            $arguments = [string]($task.Actions | Select-Object -First 1).Arguments
            $portMatch = $arguments -match '(?i)-Port\s+["'']?18789\b'
            $dataMatch = $arguments.IndexOf($ExpectedDataDir,[StringComparison]::OrdinalIgnoreCase) -ge 0
            if (-not $portMatch -or -not $dataMatch) {
                Add-Case "PRE-TASK" "BLOCKED" "environment" "Task action with port 18789 and isolated DataDir" "Mismatch" "Do not modify existing scheduled task; inspect manually"
                $safe=$false
            } else {
                Add-Case "PRE-TASK" "PASS" "environment" "Configured isolated Scheduled Task" "$ExpectedTask ($($task.State))" "No task state changed"
            }
        }
        $runtimeFile=Join-Path $ExpectedDataDir "runtime.json"
        $runtime=$null
        if (Test-Path -LiteralPath $runtimeFile -PathType Leaf) {
            $runtime=Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
        }
        $listeners=@(Get-NetTCPConnection -LocalPort $ExpectedPort -State Listen -ErrorAction SilentlyContinue)
        if (-not (Test-PortOwnership $listeners $runtime $ExpectedPort)) {
            Add-Case "PRE-PORT" "BLOCKED" "environment" "Only expected PID may listen on port 18789" "$($listeners.Count) listener(s); runtime PID unverified" "Foreign PID, absent runtime or unused port: do NOT kill, reuse or start a process"
            $safe=$false
        } else {
            Add-Case "PRE-PORT" "PASS" "environment" "All port 18789 listeners owned by isolated runtime PID" "PID $($runtime.pid); $($listeners.Count) listener(s)" "Dual-stack same-PID listener accepted; no mutation"
        }
    } catch {
        Add-Case "PRE-ISOLATION" "BLOCKED" "environment" "Task/DataDir/PID guards succeed" "Unavailable" "$($_.Exception.Message)"
        $safe=$false
    }
    try {
        $interactive=(Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName
        if (-not $interactive) {
            Add-Case "PRE-SESSION" "BLOCKED" "environment" "Interactive Windows desktop login" "Absent" "Real UI inspection cannot run headlessly"
            $safe=$false
        } else {
            Add-Case "PRE-SESSION" "PASS" "environment" "Interactive desktop user" "Present" "No session changes made"
        }
    } catch {
        Add-Case "PRE-SESSION" "BLOCKED" "environment" "Interactive desktop read-only inspection" "Unavailable" "$($_.Exception.Message)"
        $safe=$false
    }
    return $safe
}
function Test-ReadOnlyRoutes {
    $base="http://127.0.0.1:$ExpectedPort"
    $paths=@("/steam","/games","/assets/steam.js","/assets/games.js",
      "/assets/steam-ws.js","/assets/games-ws.js","/assets/ui-confirm.js",
      "/assets/node-health.js","/assets/games.css")
    $all=$true
    foreach($path in $paths) {
        try {
            $response=Invoke-WebRequest -Uri ($base+$path) -TimeoutSec 5 -UseBasicParsing
            $content=[string]$response.Content
            if([int]$response.StatusCode -ne 200 -or $content.Length -lt 50) {throw "Empty content or non-200"}
            if($path -eq "/steam" -and $content -notmatch 'steam-runtime-details') {throw "Steam Manager route missing"}
            if($path -eq "/games" -and $content -notmatch 'game-library') {throw "Game library route missing"}
            if($path -eq "/assets/ui-confirm.js" -and $content -notmatch 'gm-confirm-dialog') {throw "MagicPath modal asset absent"}
            Add-Case ("HTTP"+$path) "PASS" "product" "HTTP 200, expected non-empty asset" "Status 200, bytes $($content.Length)" "Read-only GET"
        } catch {
            Add-Case ("HTTP"+$path) "FAIL" "product" "HTTP 200, expected route/asset" "Unavailable" "$($_.Exception.Message)"
            $all=$false
        }
    }
    return $all
}
function Open-ObservationWs([string]$path) {
    $socket=[System.Net.WebSockets.ClientWebSocket]::new()
    $cancel=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($WsTimeoutSeconds))
    try {
        $socket.ConnectAsync([Uri]("ws://127.0.0.1:$ExpectedPort"+$path),$cancel.Token).GetAwaiter().GetResult()
        if($socket.State -ne [Net.WebSockets.WebSocketState]::Open){throw "WebSocket not open"}
        return $socket
    } finally { $cancel.Dispose() }
}
function Receive-JsonWs([System.Net.WebSockets.ClientWebSocket]$socket) {
    $cancel=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($WsTimeoutSeconds))
    $data=[System.Collections.Generic.List[byte]]::new()
    $chunk=New-Object byte[] 65536
    try {
        do {
            $segment=[ArraySegment[byte]]::new($chunk)
            $item=$socket.ReceiveAsync($segment,$cancel.Token).GetAwaiter().GetResult()
            if($item.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close){throw "WebSocket closed"}
            for($i=0;$i -lt $item.Count;$i++){$data.Add($chunk[$i])}
            if($data.Count -gt 524288){throw "WebSocket message size exceeds safety limit"}
        } until ($item.EndOfMessage)
        return ([Text.Encoding]::UTF8.GetString($data.ToArray()) | ConvertFrom-Json)
    } finally {$cancel.Dispose()}
}
function Request-ObservationWs([System.Net.WebSockets.ClientWebSocket]$socket,[string]$operation) {
    if($operation -notin @("games.list","steam.status")){throw "Mutating WS request forbidden"}
    $requestId="uat-"+[Guid]::NewGuid().ToString("N")
    $json=@{type="request";request_id=$requestId;operation=$operation;payload=@{}} | ConvertTo-Json -Compress
    $data=[Text.Encoding]::UTF8.GetBytes($json)
    $cancel=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($WsTimeoutSeconds))
    try {
        $socket.SendAsync([ArraySegment[byte]]::new($data),
            [Net.WebSockets.WebSocketMessageType]::Text,$true,$cancel.Token).GetAwaiter().GetResult()
    } finally {$cancel.Dispose()}
    for($i=0;$i -lt 12;$i++) {
        $msg=Receive-JsonWs $socket
        if($msg.type -eq "response" -and $msg.request_id -eq $requestId) {
            if($msg.ok -ne $true){throw "Read-only $operation returned WS error"}
            return $msg.data
        }
    }
    throw "Read-only $operation response not received"
}
function Test-ReadOnlyWebSockets {
    $gameOne=$null;$gameTwo=$null;$steam=$null
    try {
        $gameOne=Open-ObservationWs "/api/v1/games/ws"
        $gameTwo=Open-ObservationWs "/api/v1/games/ws"
        $steam=Open-ObservationWs "/api/v1/steam/ws"
        $one=Request-ObservationWs $gameOne "games.list"
        $two=Request-ObservationWs $gameTwo "games.list"
        $status=Request-ObservationWs $steam "steam.status"
        if($null -eq $one.games -or $null -eq $two.games) {
            throw "games.list response missing games collection"
        }
        Add-Case "WS-GAMES-TWO" "PASS" "product" "Two concurrent read-only WS observers" "Both returned games.list" "No synthetic changes or game operations executed"
        Add-Case "WS-STEAM" "PASS" "product" "Read-only Steam status WS response" "steam.status OK" "No Steam restart attempted"
        Add-Case "DEVF-01-AUTO" "PASS" "evidence" "Isolated A route/assets and read-only WS smoke" "GET+WS observation PASS" "Subcheck only; not a real browser on A/B"
        Add-Case "DEVF-01" "BLOCKED" "evidence" "Real browser on A must verify Steam+Games WS UI without REST polling" "Read-only subchecks passed" "Need real browser evidence; never infer full DEVF acceptance from network probes"
    } catch {
        Add-Case "WS-READONLY" "FAIL" "product" "Read-only games.list and steam.status over WS" "No valid response" "$($_.Exception.Message)"
        Add-Case "DEVF-01" "BLOCKED" "environment" "Isolated A route + WS PASS" "Incomplete" "See HTTP/WS evidence, no runtime changed"
    } finally {
        foreach($s in @($gameOne,$gameTwo,$steam)) {
            if($null -ne $s) {
                try {$s.Dispose()}catch {}
            }
        }
    }
}
try {
    if($Mode -eq "SelfTest") {
        Invoke-SelfTest
    } else {
        $ready=Test-IsolatedEnvironment
        if($ready -and $Mode -eq "ReadOnly") {
            $routes=Test-ReadOnlyRoutes
            if($routes){Test-ReadOnlyWebSockets}
            else {Add-Case "DEVF-01" "BLOCKED" "environment" "Isolated A routes/assets + WS" "HTTP failure" "WS probe skipped because required routes/assets failed"}
        } else {
            Add-Case "DEVF-01" "BLOCKED" "environment" "Verified isolated A port/task/DataDir and read-only route + WS checks" "Not executed" "ReadOnly requires PASS preflight; Preflight never probes live WS"
        }
        Add-OwnerCases
    }
} catch {
    Add-Case "RUNNER-ERROR" "FAIL" "harness" "All harness operations should be classified" "Exception" $_.Exception.Message
}
$code=Save-Report
exit $code
) { continue }
                if ($gitBranch -eq "feat/86-game-manager-ws-ui" -or
                    ($ExpectedHead -and $gitHead -eq $ExpectedHead)) {
                    $found.Add([pscustomobject]@{
                        path=$candidate.FullName; branch=$gitBranch; head=$gitHead
                    })
                }
            } catch { continue }
        }
    }
    return @($found.ToArray())
}
function Test-IsolatedEnvironment {
    $safe = $true
    try {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            throw "Git executable not found in PATH"
        }
        $issue=Get-WorktreePathIssue $RepoRoot
        if ($issue) { throw $issue }
        $branch=(& git -C $RepoRoot branch --show-current 2>&1 | Out-String).Trim()
        $head=(& git -C $RepoRoot rev-parse HEAD 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
            throw "Git checkout exists but HEAD is unreadable: $RepoRoot"
        }
        $Metadata.observed_head=$head
        if ($branch -ne "feat/86-game-manager-ws-ui" -or
            ($ExpectedHead -and $head -ne $ExpectedHead)) {
            Add-Case "PRE-HEAD" "BLOCKED" "environment" "PR #89 branch and expected HEAD" "$branch $head" "Wrong branch or HEAD. Do not switch branches automatically."
            $safe=$false
        } else {
            Add-Case "PRE-HEAD" "PASS" "environment" "PR #89 branch and expected HEAD" "$branch $head" "Worktree identity verified"
        }
    } catch {
        Add-Case "PRE-HEAD" "BLOCKED" "environment" "Git and PR #89 worktree" "$RepoRoot" $_.Exception.Message
        $safe=$false
    }
    if ($Results[$Results.Count-1].status -eq "BLOCKED") {
        $alternatives=@(Find-IsolatedPR89Worktrees)
        $Metadata["worktree_candidates"]=@($alternatives)
        if ($alternatives.Count -gt 0) {
            $shown=($alternatives | ForEach-Object { "$($_.path) [$($_.head)]" }) -join "; "
            Add-Case "PRE-WORKTREE-CANDIDATES" "PASS" "environment" "Existing PR89 checkout candidates" $shown "Use -WorktreeRoot pointing to a matching isolated checkout; never switch automatically."
        } else {
            Add-Case "PRE-WORKTREE-CANDIDATES" "BLOCKED" "environment" "Verified PR89 checkout in shallow workspace search" "None found" "Check C:\Workspace and HOME\codex-work or prepare a new isolated worktree; no checkout performed."
        }
    }
    if ($env:OS -ne "Windows_NT") {
        Add-Case "PRE-OS" "BLOCKED" "environment" "Windows A, PowerShell 7" "$($env:OS)" "UAT on A requires Windows; CI SelfTest only is allowed elsewhere"
        return $false
    }
    Add-Case "PRE-OS" "PASS" "environment" "Windows A, PowerShell 7" "Windows_NT" "Read-only Windows API preflight"
    try {
        if (-not (Test-Path -LiteralPath $ExpectedDataDir -PathType Container)) {
            Add-Case "PRE-DATADIR" "BLOCKED" "environment" "Existing isolated $ExpectedDataDir" "Missing" "No directory created by this UAT runner"
            $safe=$false
        } else {
            Add-Case "PRE-DATADIR" "PASS" "environment" "Isolated PR89 DataDir" $ExpectedDataDir "DataDir present"
        }
        $task=Get-ScheduledTask -TaskName $ExpectedTask -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            Add-Case "PRE-TASK" "BLOCKED" "environment" "Existing task $ExpectedTask" "Missing" "Runner never registers/starts tasks"
            $safe=$false
        } else {
            $arguments = [string]($task.Actions | Select-Object -First 1).Arguments
            $portMatch = $arguments -match '(?i)-Port\s+["'']?18789\b'
            $dataMatch = $arguments.IndexOf($ExpectedDataDir,[StringComparison]::OrdinalIgnoreCase) -ge 0
            if (-not $portMatch -or -not $dataMatch) {
                Add-Case "PRE-TASK" "BLOCKED" "environment" "Task action with port 18789 and isolated DataDir" "Mismatch" "Do not modify existing scheduled task; inspect manually"
                $safe=$false
            } else {
                Add-Case "PRE-TASK" "PASS" "environment" "Configured isolated Scheduled Task" "$ExpectedTask ($($task.State))" "No task state changed"
            }
        }
        $runtimeFile=Join-Path $ExpectedDataDir "runtime.json"
        $runtime=$null
        if (Test-Path -LiteralPath $runtimeFile -PathType Leaf) {
            $runtime=Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
        }
        $listeners=@(Get-NetTCPConnection -LocalPort $ExpectedPort -State Listen -ErrorAction SilentlyContinue)
        if (-not (Test-PortOwnership $listeners $runtime $ExpectedPort)) {
            Add-Case "PRE-PORT" "BLOCKED" "environment" "Only expected PID may listen on port 18789" "$($listeners.Count) listener(s); runtime PID unverified" "Foreign PID, absent runtime or unused port: do NOT kill, reuse or start a process"
            $safe=$false
        } else {
            Add-Case "PRE-PORT" "PASS" "environment" "All port 18789 listeners owned by isolated runtime PID" "PID $($runtime.pid); $($listeners.Count) listener(s)" "Dual-stack same-PID listener accepted; no mutation"
        }
    } catch {
        Add-Case "PRE-ISOLATION" "BLOCKED" "environment" "Task/DataDir/PID guards succeed" "Unavailable" "$($_.Exception.Message)"
        $safe=$false
    }
    try {
        $interactive=(Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName
        if (-not $interactive) {
            Add-Case "PRE-SESSION" "BLOCKED" "environment" "Interactive Windows desktop login" "Absent" "Real UI inspection cannot run headlessly"
            $safe=$false
        } else {
            Add-Case "PRE-SESSION" "PASS" "environment" "Interactive desktop user" "Present" "No session changes made"
        }
    } catch {
        Add-Case "PRE-SESSION" "BLOCKED" "environment" "Interactive desktop read-only inspection" "Unavailable" "$($_.Exception.Message)"
        $safe=$false
    }
    return $safe
}
function Test-ReadOnlyRoutes {
    $base="http://127.0.0.1:$ExpectedPort"
    $paths=@("/steam","/games","/assets/steam.js","/assets/games.js",
      "/assets/steam-ws.js","/assets/games-ws.js","/assets/ui-confirm.js",
      "/assets/node-health.js","/assets/games.css")
    $all=$true
    foreach($path in $paths) {
        try {
            $response=Invoke-WebRequest -Uri ($base+$path) -TimeoutSec 5 -UseBasicParsing
            $content=[string]$response.Content
            if([int]$response.StatusCode -ne 200 -or $content.Length -lt 50) {throw "Empty content or non-200"}
            if($path -eq "/steam" -and $content -notmatch 'steam-runtime-details') {throw "Steam Manager route missing"}
            if($path -eq "/games" -and $content -notmatch 'game-library') {throw "Game library route missing"}
            if($path -eq "/assets/ui-confirm.js" -and $content -notmatch 'gm-confirm-dialog') {throw "MagicPath modal asset absent"}
            Add-Case ("HTTP"+$path) "PASS" "product" "HTTP 200, expected non-empty asset" "Status 200, bytes $($content.Length)" "Read-only GET"
        } catch {
            Add-Case ("HTTP"+$path) "FAIL" "product" "HTTP 200, expected route/asset" "Unavailable" "$($_.Exception.Message)"
            $all=$false
        }
    }
    return $all
}
function Open-ObservationWs([string]$path) {
    $socket=[System.Net.WebSockets.ClientWebSocket]::new()
    $cancel=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($WsTimeoutSeconds))
    try {
        $socket.ConnectAsync([Uri]("ws://127.0.0.1:$ExpectedPort"+$path),$cancel.Token).GetAwaiter().GetResult()
        if($socket.State -ne [Net.WebSockets.WebSocketState]::Open){throw "WebSocket not open"}
        return $socket
    } finally { $cancel.Dispose() }
}
function Receive-JsonWs([System.Net.WebSockets.ClientWebSocket]$socket) {
    $cancel=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($WsTimeoutSeconds))
    $data=[System.Collections.Generic.List[byte]]::new()
    $chunk=New-Object byte[] 65536
    try {
        do {
            $segment=[ArraySegment[byte]]::new($chunk)
            $item=$socket.ReceiveAsync($segment,$cancel.Token).GetAwaiter().GetResult()
            if($item.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close){throw "WebSocket closed"}
            for($i=0;$i -lt $item.Count;$i++){$data.Add($chunk[$i])}
            if($data.Count -gt 524288){throw "WebSocket message size exceeds safety limit"}
        } until ($item.EndOfMessage)
        return ([Text.Encoding]::UTF8.GetString($data.ToArray()) | ConvertFrom-Json)
    } finally {$cancel.Dispose()}
}
function Request-ObservationWs([System.Net.WebSockets.ClientWebSocket]$socket,[string]$operation) {
    if($operation -notin @("games.list","steam.status")){throw "Mutating WS request forbidden"}
    $requestId="uat-"+[Guid]::NewGuid().ToString("N")
    $json=@{type="request";request_id=$requestId;operation=$operation;payload=@{}} | ConvertTo-Json -Compress
    $data=[Text.Encoding]::UTF8.GetBytes($json)
    $cancel=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($WsTimeoutSeconds))
    try {
        $socket.SendAsync([ArraySegment[byte]]::new($data),
            [Net.WebSockets.WebSocketMessageType]::Text,$true,$cancel.Token).GetAwaiter().GetResult()
    } finally {$cancel.Dispose()}
    for($i=0;$i -lt 12;$i++) {
        $msg=Receive-JsonWs $socket
        if($msg.type -eq "response" -and $msg.request_id -eq $requestId) {
            if($msg.ok -ne $true){throw "Read-only $operation returned WS error"}
            return $msg.data
        }
    }
    throw "Read-only $operation response not received"
}
function Test-ReadOnlyWebSockets {
    $gameOne=$null;$gameTwo=$null;$steam=$null
    try {
        $gameOne=Open-ObservationWs "/api/v1/games/ws"
        $gameTwo=Open-ObservationWs "/api/v1/games/ws"
        $steam=Open-ObservationWs "/api/v1/steam/ws"
        $one=Request-ObservationWs $gameOne "games.list"
        $two=Request-ObservationWs $gameTwo "games.list"
        $status=Request-ObservationWs $steam "steam.status"
        if($null -eq $one.games -or $null -eq $two.games) {
            throw "games.list response missing games collection"
        }
        Add-Case "WS-GAMES-TWO" "PASS" "product" "Two concurrent read-only WS observers" "Both returned games.list" "No synthetic changes or game operations executed"
        Add-Case "WS-STEAM" "PASS" "product" "Read-only Steam status WS response" "steam.status OK" "No Steam restart attempted"
        Add-Case "DEVF-01-AUTO" "PASS" "evidence" "Isolated A route/assets and read-only WS smoke" "GET+WS observation PASS" "Subcheck only; not a real browser on A/B"
        Add-Case "DEVF-01" "BLOCKED" "evidence" "Real browser on A must verify Steam+Games WS UI without REST polling" "Read-only subchecks passed" "Need real browser evidence; never infer full DEVF acceptance from network probes"
    } catch {
        Add-Case "WS-READONLY" "FAIL" "product" "Read-only games.list and steam.status over WS" "No valid response" "$($_.Exception.Message)"
        Add-Case "DEVF-01" "BLOCKED" "environment" "Isolated A route + WS PASS" "Incomplete" "See HTTP/WS evidence, no runtime changed"
    } finally {
        foreach($s in @($gameOne,$gameTwo,$steam)) {
            if($null -ne $s) {
                try {$s.Dispose()}catch {}
            }
        }
    }
}
try {
    if($Mode -eq "SelfTest") {
        Invoke-SelfTest
    } else {
        $ready=Test-IsolatedEnvironment
        if($ready -and $Mode -eq "ReadOnly") {
            $routes=Test-ReadOnlyRoutes
            if($routes){Test-ReadOnlyWebSockets}
            else {Add-Case "DEVF-01" "BLOCKED" "environment" "Isolated A routes/assets + WS" "HTTP failure" "WS probe skipped because required routes/assets failed"}
        } else {
            Add-Case "DEVF-01" "BLOCKED" "environment" "Verified isolated A port/task/DataDir and read-only route + WS checks" "Not executed" "ReadOnly requires PASS preflight; Preflight never probes live WS"
        }
        Add-OwnerCases
    }
} catch {
    Add-Case "RUNNER-ERROR" "FAIL" "harness" "All harness operations should be classified" "Exception" $_.Exception.Message
}
$code=Save-Report
exit $code
