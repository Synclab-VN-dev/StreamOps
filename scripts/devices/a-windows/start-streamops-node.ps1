# StreamOps-managed interactive-session start script.
[CmdletBinding()]
param(
    [string]$TaskName = "StreamOps Node (repo-local)",
    [string]$BindHost = "0.0.0.0",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(0, 2147483647)]
    [int]$OutputIndex = 0,
    [string]$DataDir,
    [string]$PythonPath,
    [ValidateRange(0.01, 30)]
    [double]$CaptureTimeout = 3,
    [ValidateSet("critical", "error", "warning", "info", "debug", "trace")]
    [string]$LogLevel = "info",
    [ValidateSet("", "github-release", "directory")]
    [string]$ObsPluginSourceProvider = "github-release",
    [string]$ObsPluginSourceLocation = "Synclab-VN-dev/StreamOps-OBS-Plugins",
    [string]$ObsPluginGitHubTokenEnv = "STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN",
    [switch]$NoGitHubTokenPrompt,
    [switch]$GitHubTokenFromClipboard
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$launcher = Join-Path $PSScriptRoot "run-streamops-node.ps1"
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
if ($null -ne $existingTask) {
    $taskUsesNormalPriority = [int]$existingTask.Settings.Priority -eq 4
    $taskAction = $existingTask.Actions | Select-Object -First 1
    if ($null -ne $taskAction) {
        $taskArgumentsText = [string]$taskAction.Arguments
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
        $matchesDesiredConfig = $taskUsesPythonPath -and $taskUsesPluginSource -and $taskUsesNormalPriority -and
            $runtime.host -eq $BindHost -and
            [int]$runtime.port -eq $Port -and
            [int]$runtime.output_index -eq $OutputIndex -and
            [double]$runtime.capture_timeout -eq $CaptureTimeout -and
            $runtime.log_level -eq $LogLevel
        if ($matchesDesiredConfig -and $health.status -eq "ok" -and $health.capture_ready -and
            $health.session_id -eq $health.active_console_session_id) {
            Write-Host "streamops-node is already running in interactive session $($health.session_id) with $($health.capture_backend) capture (PID $($runtime.pid))."
            exit 0
        }
    }
    catch {
        # The stale or unhealthy process is reconciled below.
    }
    & (Join-Path $PSScriptRoot "stop-streamops-node.ps1") -DataDir $DataDir -TaskName $TaskName
}

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
            & (Join-Path $PSScriptRoot "protect-obs-plugin-token-dir.ps1") -Directory $secretDir
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
    "-File", (ConvertTo-TaskArgument $launcher),
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
            exit 0
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
& (Join-Path $PSScriptRoot "stop-streamops-node.ps1") -DataDir $DataDir -TaskName $TaskName
$result = if ($null -eq $taskInfo) { "unknown" } else { $taskInfo.LastTaskResult }
throw "streamops-node did not become capture-ready in the interactive session. Task result: $result"
