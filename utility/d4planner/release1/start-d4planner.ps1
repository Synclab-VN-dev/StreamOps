[CmdletBinding()]
param(
    [string]$InstallRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'StreamOps\D4Planner'),
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$targetRoot = Join-Path $DataRoot 'targets'
$stateRoot = Join-Path $DataRoot 'state'
$privateRoot = Join-Path $DataRoot 'private'
New-Item -ItemType Directory -Force $targetRoot, $stateRoot, $privateRoot | Out-Null

$bootstrap = Join-Path $privateRoot ("bootstrap-{0}.json" -f [guid]::NewGuid())
$credentialBytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($credentialBytes) } finally { $rng.Dispose() }
$credential = ([BitConverter]::ToString($credentialBytes) -replace '-', '').ToLowerInvariant()
$descriptor = [ordered]@{
    protocol = 'd4planner-managed/v1'
    contractVersion = 'd4planner-r1-contract/1.0.0-candidate.5'
    ownerInstanceId = [guid]::NewGuid().ToString()
    childInstanceId = [guid]::NewGuid().ToString()
    generation = 1
    dataDir = $stateRoot
    targetFolder = $targetRoot
    repositoryRoot = $InstallRoot
    wsEndpoint = @{ host = '127.0.0.1'; port = 0 }
    credential = $credential
}
[IO.File]::WriteAllText($bootstrap, ($descriptor | ConvertTo-Json -Depth 4 -Compress), [Text.UTF8Encoding]::new($false))

$env:D4PLANNER_BOOTSTRAP_FILE = $bootstrap
$env:D4PLANNER_BACKEND_PYTHON = Join-Path $InstallRoot 'runtime\python\python.exe'
$env:PYTHONPATH = Join-Path $InstallRoot 'backend\site-packages'
$env:D4PLANNER_REPOSITORY_ROOT = $InstallRoot
$env:D4PLANNER_RULEKIT_EXECUTABLE = Join-Path $InstallRoot 'runtime\node\node.exe'
$env:D4PLANNER_RULEKIT_WORKER = Join-Path $InstallRoot 'utility\d4planner\rulekit-worker\worker.js'
$env:D4PLANNER_RULEKIT_WORKING_DIR = Join-Path $InstallRoot 'utility\d4planner\rulekit-worker'
$env:D4_RULEKIT_PROFILE_JSON = Join-Path $InstallRoot 'config\maxroll-profile.json'
$env:D4_RULEKIT_SNAPSHOT_ROOT = Join-Path $InstallRoot 'runtime\snapshots'
$env:D4_RULEKIT_CHROMIUM_EXECUTABLE = Join-Path $InstallRoot 'runtime\chromium\chrome-win64\chrome.exe'

$frontend = Join-Path $InstallRoot 'app\d4planner-fe.exe'
if (-not (Test-Path -LiteralPath $frontend -PathType Leaf)) { throw "Native FE missing: $frontend" }
try {
    $start = @{ FilePath = $frontend; WorkingDirectory = $InstallRoot; PassThru = $true; Wait = $true }
    if ($SelfTest) { $start.ArgumentList = @('--self-test') }
    $process = Start-Process @start
    exit $process.ExitCode
}
finally {
    Remove-Item -LiteralPath $bootstrap -Force -ErrorAction SilentlyContinue
}
