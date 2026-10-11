# StreamOps-managed repo-local Scheduled Task action.
[CmdletBinding()]
param(
    [string]$BindHost = "0.0.0.0",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(0, 2147483647)]
    [int]$OutputIndex = 0,
    [Parameter(Mandatory)]
    [string]$DataDir,
    [string]$PythonPath,
    [ValidateRange(0.01, 30)]
    [double]$CaptureTimeout = 3,
    [ValidateSet("critical", "error", "warning", "info", "debug", "trace")]
    [string]$LogLevel = "info",
    [ValidateSet("", "github-release", "directory")]
    [string]$ObsPluginSourceProvider = "",
    [string]$ObsPluginSourceLocation = "",
    [string]$ObsPluginGitHubTokenEnv = "",
    [string]$ObsPluginCredentialFile = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
