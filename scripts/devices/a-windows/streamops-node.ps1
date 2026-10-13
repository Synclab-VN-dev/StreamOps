#requires -Version 7.0
# One operator entrypoint. The __run action is reserved for our Scheduled Task.
# Usage: .\streamops-node.ps1 start | stop | status
[CmdletBinding()]
param(
    [Parameter(Position=0)][ValidateSet("start","stop","status","__run")][string]$Action = "status",
    [string]$TaskName = "StreamOps Node (repo-local)",
    [string]$BindHost = "0.0.0.0",
    [ValidateRange(1,65535)][int]$Port = 8765,
    [ValidateRange(0,2147483647)][int]$OutputIndex = 0,
    [string]$DataDir,
    [string]$PythonPath,
    [ValidateRange(0.01,30)][double]$CaptureTimeout = 3,
    [ValidateSet("critical","error","warning","info","debug","trace")][string]$LogLevel = "info",
    [ValidateSet("","github-release","directory")][string]$ObsPluginSourceProvider = "",
    [string]$ObsPluginSourceLocation = "Synclab-VN-dev/StreamOps-OBS-Plugins",
    [string]$ObsPluginGitHubTokenEnv = "STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN",
    [switch]$NoGitHubTokenPrompt,
    [switch]$GitHubTokenFromClipboard,
    [string]$ObsPluginCredentialFile
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# A task name alone is not proof of ownership. Accept the current one-file task
# or the previous repo-local runner (migration), but never a different worktree.
function Assert-NodeTaskOwned {
    param([Parameter(Mandatory)]$Task, [Parameter(Mandatory)][string]$ExpectedDataDir)
    $action = $Task.Actions | Select-Object -First 1
    if ($null -eq $action) { throw "Scheduled Task has no action." }
    $taskArgsText = [string]$action.Arguments
    $legacyRunner = Join-Path $PSScriptRoot "run-streamops-node.ps1"
    $newRunnerValid = $taskArgsText.IndexOf($PSCommandPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $taskArgsText.Contains("__run")
    $legacyRunnerValid = $taskArgsText.IndexOf($legacyRunner, [StringComparison]::OrdinalIgnoreCase) -ge 0
    if (-not ($newRunnerValid -or $legacyRunnerValid) -or
        -not $taskArgsText.Contains("-DataDir") -or
        $taskArgsText.IndexOf($ExpectedDataDir, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Refusing task operation: Scheduled Task does not belong to this launcher/DataDir."
    }
}

function Protect-TokenDirectory {
    param([Parameter(Mandatory)][string]$Directory)
$item = Get-Item -LiteralPath $Directory -Force -ErrorAction Stop
if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "Token handoff directory must be a real local directory."
}

# The scheduled task runs as the SAME Windows interactive user. The current
# SID avoids account-name escaping/localization issues for domain users.
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$grant = "*" + $sid + ":(OI)(CI)F"

# icacls changes the DACL only; a newly created DirectorySecurity object
# passed to Set-Acl can attempt SACL changes requiring SeSecurityPrivilege.
# Grant before removing inherited ACLs so the directory never loses owner access.
& icacls.exe $item.FullName "/grant:r" $grant "/inheritance:r" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restrict token handoff directory ACL (icacls exit $LASTEXITCODE)."
}

# Windows can give newly created directories explicit ACL entries for
# SYSTEM/Administrators/other principals, not just inherited entries.
# Remove those explicit grants/denials by SID, while retaining this user's
# explicit grant. Do not widen privileges or disable the ACL verification.
$acl = Get-Acl -LiteralPath $item.FullName -ErrorAction Stop
if (-not $acl.AreAccessRulesProtected) {
    throw "Token handoff directory still inherits permissions."
}
$existingRules = $acl.GetAccessRules(
    $true, $true, [System.Security.Principal.SecurityIdentifier]
)
$otherSids = @(
    $existingRules |
        Where-Object { $_.IdentityReference.Value -ne $sid } |
        ForEach-Object { $_.IdentityReference.Value } |
        Sort-Object -Unique
)
foreach ($otherSid in $otherSids) {
    & icacls.exe $item.FullName "/remove" ("*" + $otherSid) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove an unexpected token handoff ACL entry."
    }
}
# Never write the token until the final DACL is exactly owner-only.
$acl = Get-Acl -LiteralPath $item.FullName -ErrorAction Stop
$rules = $acl.GetAccessRules(
    $true, $true, [System.Security.Principal.SecurityIdentifier]
)
$ownAllow = $false
foreach ($rule in $rules) {
    if ($rule.IsInherited -or $rule.AccessControlType -ne "Allow" -or
        $rule.IdentityReference.Value -ne $sid) {
        throw "Token handoff directory has unexpected permissions."
    }
    $ownAllow = $true
}
if (-not $ownAllow) {
    throw "Token handoff directory did not grant the interactive user access."
}
}

function Invoke-NodeRun {
    if ([string]::IsNullOrWhiteSpace($DataDir)) { throw "Internal runner requires -DataDir." }
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$python = if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    Join-Path $repoRoot ".venv\Scripts\python.exe"
} elseif ([IO.Path]::IsPathRooted($PythonPath)) {
    [IO.Path]::GetFullPath($PythonPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $repoRoot $PythonPath))
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Configured Python interpreter is missing: $python"
}

$DataDir = [IO.Path]::GetFullPath($DataDir)
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $DataDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDir must stay inside the repository: $repoRoot"
}
if (-not $python.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "PythonPath must stay inside the repository-managed runtime area: $repoRoot"
}

$logDir = Join-Path $DataDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutLog = Join-Path $logDir "node-$timestamp.stdout.log"
$stderrLog = Join-Path $logDir "node-$timestamp.stderr.log"
$arguments = @(
    "-m", "streamops.cli", "runserver",
    "--host", $BindHost,
    "--port", $Port,
    "--output-index", $OutputIndex,
    "--data-dir", $DataDir,
    "--capture-timeout", $CaptureTimeout.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--log-level", $LogLevel
)

if (-not [string]::IsNullOrWhiteSpace($ObsPluginSourceProvider)) {
    if ([string]::IsNullOrWhiteSpace($ObsPluginSourceLocation)) {
        throw "ObsPluginSourceLocation is required when a provider is configured."
    }
    $env:STREAMOPS_OBS_PLUGIN_SOURCE_PROVIDER = $ObsPluginSourceProvider
    $env:STREAMOPS_OBS_PLUGIN_SOURCE_LOCATION = $ObsPluginSourceLocation
    if ($ObsPluginSourceProvider -eq "github-release") {
        # A Scheduled Task does not inherit the invoking SSH/PowerShell shell's
        # environment. Receive a short-lived DPAPI-encrypted handoff instead.
        $credentialEnv = if ($ObsPluginGitHubTokenEnv) {
            $ObsPluginGitHubTokenEnv
        } else {
            "STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN"
        }
        if ($credentialEnv -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw "ObsPluginGitHubTokenEnv must be an environment variable name."
        }
        $env:STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN_ENV = $credentialEnv
        if ($ObsPluginCredentialFile) {
            # Always delete the encrypted handoff, even if decryption fails.
            try {
                if (-not (Test-Path -LiteralPath $ObsPluginCredentialFile -PathType Leaf)) {
                    throw "Token handoff file was not found."
                }
                $encrypted = Get-Content -LiteralPath $ObsPluginCredentialFile -Raw
                $secret = ConvertTo-SecureString ($encrypted.Trim())
                $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
                try {
                    $plaintext = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
                    [Environment]::SetEnvironmentVariable($credentialEnv, $plaintext, "Process")
                }
                finally {
                    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
                    $plaintext = $null
                }
            }
            finally {
                Remove-Item -LiteralPath $ObsPluginCredentialFile -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Push-Location $DataDir
try {
    & $python @arguments 1>> $stdoutLog 2>> $stderrLog
    return $LASTEXITCODE
}
finally {
    Pop-Location
}
}

function Invoke-NodeStop {
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

function Get-RepoOwnedProcess([int]$ProcessId) {
    $candidate = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $candidate) {
        return $null
    }
    if (-not [string]::IsNullOrWhiteSpace($candidate.Path) -and
        $candidate.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $candidate
    }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        return $null
    }
    $parent = Get-Process -Id $processInfo.ParentProcessId -ErrorAction SilentlyContinue
    if ($null -ne $parent -and -not [string]::IsNullOrWhiteSpace($parent.Path) -and
        $parent.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $candidate
    }
    return $null
}
if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $repoRoot ".streamops\node"
}
elseif (-not [IO.Path]::IsPathRooted($DataDir)) {
    $DataDir = [IO.Path]::GetFullPath((Join-Path $repoRoot $DataDir))
}
$DataDir = [IO.Path]::GetFullPath($DataDir)
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $DataDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDir must stay inside the repository: $repoRoot"
}

$runtimePath = Join-Path $DataDir "runtime.json"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $task) { Assert-NodeTaskOwned -Task $task -ExpectedDataDir $DataDir }
if ($null -ne $task -and $task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -eq $task -or $task.State -ne "Running") {
            break
        }
    }
}

if (-not (Test-Path -LiteralPath $runtimePath)) {
    Write-Host "streamops-node is already stopped."
    return 0
}

$runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
$runningProcess = Get-Process -Id $runtime.pid -ErrorAction SilentlyContinue
if ($null -eq $runningProcess) {
    Remove-Item -LiteralPath $runtimePath -Force
    Write-Host "Removed stale runtime state; streamops-node was not running."
    return 0
}

if ($null -eq (Get-RepoOwnedProcess $runtime.pid)) {
    throw "Refusing to stop PID $($runtime.pid): its executable is not owned by this repository."
}

Stop-Process -Id $runtime.pid -Force
Wait-Process -Id $runtime.pid -Timeout 10 -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $runtimePath) {
    $current = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
    if ($current.pid -eq $runtime.pid) {
        Remove-Item -LiteralPath $runtimePath -Force
    }
}
Write-Host "streamops-node stopped (PID $($runtime.pid))."
}

function Invoke-NodeStatus {
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

function Test-RepoOwnedProcess([int]$ProcessId) {
    $candidate = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $candidate) {
        return $false
    }
    if (-not [string]::IsNullOrWhiteSpace($candidate.Path) -and
        $candidate.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        return $false
    }
    $parent = Get-Process -Id $processInfo.ParentProcessId -ErrorAction SilentlyContinue
    return $null -ne $parent -and -not [string]::IsNullOrWhiteSpace($parent.Path) -and
        $parent.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)
}

function Get-ProbeHost([string]$HostName) {
    if ($HostName -ne "0.0.0.0") {
        return $HostName
    }

    $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" `
        -ErrorAction SilentlyContinue | Sort-Object RouteMetric
    foreach ($route in $routes) {
        $address = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex `
            -AddressState Preferred -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
            Select-Object -First 1
        if ($null -ne $address) {
            return $address.IPAddress
        }
    }

    $address = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1
    if ($null -ne $address) {
        return $address.IPAddress
    }
    return "127.0.0.1"
}
if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $repoRoot ".streamops\node"
}
elseif (-not [IO.Path]::IsPathRooted($DataDir)) {
    $DataDir = [IO.Path]::GetFullPath((Join-Path $repoRoot $DataDir))
}
$DataDir = [IO.Path]::GetFullPath($DataDir)
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $DataDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDir must stay inside the repository: $repoRoot"
}

$runtimePath = Join-Path $DataDir "runtime.json"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskState = if ($null -eq $task) { "NotRegistered" } else { [string]$task.State }
if (-not (Test-Path -LiteralPath $runtimePath)) {
    Write-Host "streamops-node is not running (task $taskState, no runtime state)."
    return 1
}

$runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
$process = Get-Process -Id $runtime.pid -ErrorAction SilentlyContinue
if ($null -eq $process -or -not (Test-RepoOwnedProcess $runtime.pid)) {
    Write-Host "streamops-node is not running (stale runtime state for PID $($runtime.pid))."
    return 1
}

$probeHost = Get-ProbeHost $runtime.host
$healthUrl = "http://${probeHost}:$($runtime.port)/api/v1/health"
try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
}
catch {
    Write-Host "streamops-node process $($runtime.pid) exists but health check failed: $healthUrl"
    return 1
}

if ($health.session_id -ne $health.active_console_session_id) {
    Write-Host "streamops-node is in the wrong desktop session ($($health.session_id); active $($health.active_console_session_id))."
    return 1
}
if (-not $health.capture_ready) {
    Write-Host "streamops-node is online in session $($health.session_id), but capture is unavailable."
    return 1
}

Write-Host "streamops-node is running (PID $($runtime.pid), session $($health.session_id), port $($runtime.port), output $($runtime.output_index), capture $($health.capture_backend))."
Write-Host "Task: $TaskName ($taskState)"
Write-Host "Health: $healthUrl"
return 0
}

function Invoke-NodeStart {
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$launcher = $PSCommandPath
$pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
elseif (-not [IO.Path]::IsPathRooted($PythonPath)) {
    $PythonPath = [IO.Path]::GetFullPath((Join-Path $repoRoot $PythonPath))
}
$PythonPath = [IO.Path]::GetFullPath($PythonPath)
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Configured Python interpreter is missing: $PythonPath"
}
if (-not $PythonPath.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "PythonPath must stay inside the repository-managed runtime area: $repoRoot"
}

function ConvertTo-TaskArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Read-GitHubTokenFromClipboard {
    $secure = $null
    $clipboardText = $null
    $clipboardLines = $null
    try {
        $clipboardLines = @(Get-Clipboard -ErrorAction Stop)
        if ($clipboardLines.Count -ne 1) {
            throw "Clipboard must contain exactly one token line."
        }
        $clipboardText = [string]$clipboardLines[0]
        if ([string]::IsNullOrWhiteSpace($clipboardText) -or
            $clipboardText -match '[\s\x00-\x1f\x7f]') {
            throw "Clipboard token is empty or contains whitespace/control characters."
        }
        $secure = ConvertTo-SecureString -String $clipboardText -AsPlainText -Force
    }
    finally {
        $clipboardText = $null
        $clipboardLines = $null
        # Clear the active clipboard after the read, including invalid content.
        # Clipboard History/cloud sync cannot be cleared by this operation.
        try {
            Set-Clipboard -Value " " -ErrorAction Stop
        }
        catch {
            if ($null -ne $secure) { $secure.Dispose() }
            throw "Could not clear Windows clipboard after reading token."
        }
    }
    return $secure
}

function Get-ProbeHost([string]$HostName) {
    if ($HostName -ne "0.0.0.0") {
        return $HostName
    }

    $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" `
        -ErrorAction SilentlyContinue | Sort-Object RouteMetric
    foreach ($route in $routes) {
        $address = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex `
            -AddressState Preferred -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
            Select-Object -First 1
        if ($null -ne $address) {
            return $address.IPAddress
        }
    }

    $address = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1
    if ($null -ne $address) {
        return $address.IPAddress
    }
    return "127.0.0.1"
}

if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $repoRoot ".streamops\node"
}
elseif (-not [IO.Path]::IsPathRooted($DataDir)) {
    $DataDir = [IO.Path]::GetFullPath((Join-Path $repoRoot $DataDir))
}
$DataDir = [IO.Path]::GetFullPath($DataDir)
if (-not $DataDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDir must stay inside the repository: $repoRoot"
}

$interactiveUser = (Get-CimInstance Win32_ComputerSystem).UserName
if ([string]::IsNullOrWhiteSpace($interactiveUser)) {
    throw "No interactive Windows user is logged on; screen capture cannot start."
}

$runtimePath = Join-Path $DataDir "runtime.json"
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskUsesPythonPath = $false
$taskUsesPluginSource = $false
$taskUsesNormalPriority = $false
$taskUsesConsolidatedLauncher = $false
if ($null -ne $existingTask) {
    Assert-NodeTaskOwned -Task $existingTask -ExpectedDataDir $DataDir
    $taskUsesNormalPriority = [int]$existingTask.Settings.Priority -eq 4
    $taskAction = $existingTask.Actions | Select-Object -First 1
    if ($null -ne $taskAction) {
        $taskArgumentsText = [string]$taskAction.Arguments
        $taskUsesConsolidatedLauncher = $taskArgumentsText.IndexOf($PSCommandPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $taskArgumentsText.Contains("__run")
        $taskUsesPythonPath = $taskArgumentsText.Contains("-PythonPath") -and
            $taskArgumentsText.IndexOf($PythonPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
        if ([string]::IsNullOrWhiteSpace($ObsPluginSourceProvider)) {
            $taskUsesPluginSource = -not $taskArgumentsText.Contains("-ObsPluginSourceProvider")
        }
        else {
            $taskUsesPluginSource = $taskArgumentsText.Contains("-ObsPluginSourceProvider") -and
                $taskArgumentsText.IndexOf($ObsPluginSourceProvider, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $taskArgumentsText.IndexOf($ObsPluginSourceLocation, [StringComparison]::OrdinalIgnoreCase) -ge 0
            if (-not [string]::IsNullOrWhiteSpace($ObsPluginGitHubTokenEnv)) {
                $taskUsesPluginSource = $taskUsesPluginSource -and
                    $taskArgumentsText.IndexOf($ObsPluginGitHubTokenEnv, [StringComparison]::OrdinalIgnoreCase) -ge 0
            }
        }
    }
}
if (Test-Path -LiteralPath $runtimePath) {
    try {
        $runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
        $probeHost = Get-ProbeHost $runtime.host
        $health = Invoke-RestMethod -Uri "http://${probeHost}:$($runtime.port)/api/v1/health" -TimeoutSec 2
        $matchesDesiredConfig = $taskUsesConsolidatedLauncher -and $taskUsesPythonPath -and $taskUsesPluginSource -and $taskUsesNormalPriority -and
            $runtime.host -eq $BindHost -and
            [int]$runtime.port -eq $Port -and
            [int]$runtime.output_index -eq $OutputIndex -and
            [double]$runtime.capture_timeout -eq $CaptureTimeout -and
            $runtime.log_level -eq $LogLevel
        if ($matchesDesiredConfig -and $health.status -eq "ok" -and $health.capture_ready -and
            $health.session_id -eq $health.active_console_session_id) {
            Write-Host "streamops-node is already running in interactive session $($health.session_id) with $($health.capture_backend) capture (PID $($runtime.pid))."
            return 0
        }
    }
    catch {
        # The stale or unhealthy process is reconciled below.
    }
    Invoke-NodeStop | Out-Null
}

# Fail closed if another application currently owns this port.
$occupied = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($occupied.Count -gt 0) { throw "Port $Port is already listening; refusing to replace an unknown service." }

# Prompt only when actually starting/restarting the node. Scheduled Tasks do
# not inherit the SSH terminal environment. A one-use DPAPI handoff is readable
# only by the same Windows user and never appears in task arguments or logs.
if ($GitHubTokenFromClipboard -and ($NoGitHubTokenPrompt -or $ObsPluginSourceProvider -ne "github-release")) {
    throw "GitHubTokenFromClipboard requires github-release and cannot be combined with NoGitHubTokenPrompt."
}
$tokenHandoff = $null
if ($ObsPluginSourceProvider -eq "github-release" -and -not $NoGitHubTokenPrompt) {
    $secureToken = $null
    if ($GitHubTokenFromClipboard) {
        $secureToken = Read-GitHubTokenFromClipboard
        Write-Host "GitHub token taken from clipboard (value hidden; active clipboard cleared)."
    }
    else {
        $redirected = $true
        try { $redirected = [Console]::IsInputRedirected } catch { }
        if (-not $redirected) {
            $secureToken = Read-Host "GitHub read-only token for managed OBS plugins (Enter to skip)" -AsSecureString
        }
    }
    try {
        if ($null -ne $secureToken -and $secureToken.Length -gt 0) {
            $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
            if (-not [string]::Equals($currentUser, $interactiveUser, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Token handoff requires the startup shell to run as the logged-in desktop user: $interactiveUser"
            }
            $secretDir = Join-Path $DataDir ".secrets"
            New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
            # Restrict only the directory DACL. No SeSecurityPrivilege or
            # Administrator rights are needed by the interactive desktop user.
            # The helper checks the resulting owner-only ACL before token I/O.
            Protect-TokenDirectory -Directory $secretDir
            $tokenHandoff = Join-Path $secretDir ("github-token-" + [Guid]::NewGuid().ToString("N") + ".dpapi")
            # ConvertFrom-SecureString uses Windows CurrentUser DPAPI (no key).
            [IO.File]::WriteAllText($tokenHandoff, (ConvertFrom-SecureString $secureToken))
            Write-Host "GitHub token captured securely for this server start (value hidden)."
        }
    }
    finally {
        if ($null -ne $secureToken) { $secureToken.Dispose() }
    }
    if (-not $tokenHandoff) {
        Write-Warning "GitHub token missing; OBS Plugin Manager catalog will report plugin_github_token_missing until the node is restarted with a token."
    }
}

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask -and $existingTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
}

$actionArguments = @(
    "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", (ConvertTo-TaskArgument $launcher), "__run",
    "-BindHost", (ConvertTo-TaskArgument $BindHost),
    "-Port", $Port,
    "-OutputIndex", $OutputIndex,
    "-DataDir", (ConvertTo-TaskArgument $DataDir),
    "-PythonPath", (ConvertTo-TaskArgument $PythonPath),
    "-CaptureTimeout", $CaptureTimeout.ToString([Globalization.CultureInfo]::InvariantCulture),
    "-LogLevel", $LogLevel
) -join " "

if (-not [string]::IsNullOrWhiteSpace($ObsPluginSourceProvider)) {
    if ([string]::IsNullOrWhiteSpace($ObsPluginSourceLocation)) {
        throw "ObsPluginSourceLocation is required when a provider is configured."
    }
    $actionArguments += " -ObsPluginSourceProvider " + (ConvertTo-TaskArgument $ObsPluginSourceProvider)
    $actionArguments += " -ObsPluginSourceLocation " + (ConvertTo-TaskArgument $ObsPluginSourceLocation)
    if (-not [string]::IsNullOrWhiteSpace($ObsPluginGitHubTokenEnv)) {
        $actionArguments += " -ObsPluginGitHubTokenEnv " + (ConvertTo-TaskArgument $ObsPluginGitHubTokenEnv)
    }
    if ($tokenHandoff) {
        $actionArguments += " -ObsPluginCredentialFile " + (ConvertTo-TaskArgument $tokenHandoff)
    }
}

$action = New-ScheduledTaskAction -Execute $pwsh -Argument $actionArguments -WorkingDirectory $repoRoot
$principal = New-ScheduledTaskPrincipal -UserId $interactiveUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -Priority 4 `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$definition = New-ScheduledTask `
    -Action $action `
    -Principal $principal `
    -Settings $settings `
    -Description "Repo-local StreamOps node; started on demand in the interactive desktop session."
Register-ScheduledTask -TaskName $TaskName -InputObject $definition -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

$probeHost = Get-ProbeHost $BindHost
$healthUrl = "http://${probeHost}:$Port/api/v1/health"
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
        if ($health.status -eq "ok" -and $health.capture_ready -and
            $health.session_id -eq $health.active_console_session_id) {
            if ($tokenHandoff) { Remove-Item -LiteralPath $tokenHandoff -Force -ErrorAction SilentlyContinue }
            $runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
            Write-Host "streamops-node is running (PID $($runtime.pid), session $($health.session_id), capture $($health.capture_backend)): $healthUrl"
            Write-Host "Task: $TaskName"
            Write-Host "Logs: $(Join-Path $DataDir 'logs')"
            return 0
        }
        if (-not $health.capture_ready -and $attempt % 10 -eq 0) {
            try {
                Invoke-RestMethod -Method Post -Uri "http://${probeHost}:$Port/api/v1/screen/capture" `
                    -TimeoutSec ([Math]::Ceiling($CaptureTimeout * 2 + 2)) | Out-Null
            }
            catch {
                # Capture errors are reported after the readiness deadline.
            }
        }
    }
    catch {
        # The task may still be starting.
    }
}

$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
if ($tokenHandoff) { Remove-Item -LiteralPath $tokenHandoff -Force -ErrorAction SilentlyContinue }
Invoke-NodeStop | Out-Null
$result = if ($null -eq $taskInfo) { "unknown" } else { $taskInfo.LastTaskResult }
throw "streamops-node did not become capture-ready in the interactive session. Task result: $result"
}

try {
    switch ($Action) {
        "start" {
            if (-not $PSBoundParameters.ContainsKey("ObsPluginSourceProvider")) {
                $ObsPluginSourceProvider = "github-release"
            }
            exit (Invoke-NodeStart)
        }
        "stop" { exit (Invoke-NodeStop) }
        "status" { exit (Invoke-NodeStatus) }
        "__run" { exit (Invoke-NodeRun) }
    }
}
catch {
    [Console]::Error.WriteLine(("streamops-node {0} failed: {1}" -f $Action, $_.Exception.Message))
    exit 1
}
