[CmdletBinding()]
param(
    [string]$InstallRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'StreamOps\D4Planner'),
    [string]$TargetFolder = '',
    [ValidateSet('Dynamic', 'FixedApprovedUat')][string]$WsPortMode = 'Dynamic',
    [ValidateRange(0, 65535)][int]$ApprovedPort = 0,
    [string]$EquipmentRepositoryDb = '',
    [switch]$EnableReadOnlyEquipmentRepository,
    [string]$CharacterId = '',
    [string]$CharacterDisplayName = '',
    [switch]$ValidateOnly,
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$targetRoot = if ($TargetFolder) { [IO.Path]::GetFullPath($TargetFolder) } else { Join-Path $DataRoot 'targets' }
$stateRoot = Join-Path $DataRoot 'state'
$privateRoot = Join-Path $DataRoot 'private'
New-Item -ItemType Directory -Force $targetRoot, $stateRoot, $privateRoot | Out-Null

if ($WsPortMode -eq 'FixedApprovedUat' -and $ApprovedPort -eq 0) {
    throw 'FixedApprovedUat requires an Owner-approved non-zero -ApprovedPort'
}
if ($WsPortMode -eq 'Dynamic' -and $ApprovedPort -ne 0) {
    throw '-ApprovedPort is valid only with -WsPortMode FixedApprovedUat'
}
if ($EnableReadOnlyEquipmentRepository) {
    if (-not $EquipmentRepositoryDb) { throw '-EquipmentRepositoryDb is required when read-only capture is enabled' }
    $EquipmentRepositoryDb = [IO.Path]::GetFullPath($EquipmentRepositoryDb)
    if (-not (Test-Path -LiteralPath $EquipmentRepositoryDb -PathType Leaf)) {
        throw "Read-only Equipment database does not exist: $EquipmentRepositoryDb"
    }
    if ([string]::IsNullOrWhiteSpace($CharacterId) -or [string]::IsNullOrWhiteSpace($CharacterDisplayName)) {
        throw '-CharacterId and -CharacterDisplayName are required when read-only capture is enabled'
    }
    if ($CharacterId.Length -gt 160 -or $CharacterDisplayName.Length -gt 160) {
        throw 'Character identity fields must be 160 characters or fewer'
    }
} elseif ($EquipmentRepositoryDb) {
    throw '-EquipmentRepositoryDb requires -EnableReadOnlyEquipmentRepository'
} elseif ($CharacterId -or $CharacterDisplayName) {
    throw 'Character identity is valid only with -EnableReadOnlyEquipmentRepository'
}

$frontend = Join-Path $InstallRoot 'app\d4planner-fe.exe'
if (-not (Test-Path -LiteralPath $frontend -PathType Leaf)) { throw "Native FE missing: $frontend" }
$backendPython = Join-Path $InstallRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) { throw "Private Python missing: $backendPython" }

if ($ValidateOnly) {
    [ordered]@{
        ok = $true; installRoot = $InstallRoot; dataRoot = $DataRoot; targetFolder = $targetRoot
        wsPortMode = $WsPortMode; approvedPort = $ApprovedPort
        equipmentRepository = if ($EnableReadOnlyEquipmentRepository) { $EquipmentRepositoryDb } else { $null }
        characterId = if ($EnableReadOnlyEquipmentRepository) { $CharacterId } else { $null }
        characterDisplayName = if ($EnableReadOnlyEquipmentRepository) { $CharacterDisplayName } else { $null }
    } | ConvertTo-Json -Compress
    exit 0
}

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
    wsEndpoint = @{ host = '127.0.0.1'; port = $(if ($WsPortMode -eq 'Dynamic') { 0 } else { $ApprovedPort }) }
    credential = $credential
}
[IO.File]::WriteAllText($bootstrap, ($descriptor | ConvertTo-Json -Depth 4 -Compress), [Text.UTF8Encoding]::new($false))

$env:D4PLANNER_BOOTSTRAP_FILE = $bootstrap
$env:D4PLANNER_BACKEND_PYTHON = $backendPython
$env:PYTHONPATH = Join-Path $InstallRoot 'backend\site-packages'
$env:D4PLANNER_REPOSITORY_ROOT = $InstallRoot
$env:D4PLANNER_RULEKIT_EXECUTABLE = Join-Path $InstallRoot 'runtime\node\node.exe'
$env:D4PLANNER_RULEKIT_WORKER = Join-Path $InstallRoot 'utility\d4planner\rulekit-worker\worker.js'
$env:D4PLANNER_RULEKIT_WORKING_DIR = Join-Path $InstallRoot 'utility\d4planner\rulekit-worker'
$env:D4_RULEKIT_PROFILE_JSON = Join-Path $InstallRoot 'config\maxroll-profile.json'
$env:D4_RULEKIT_SNAPSHOT_ROOT = Join-Path $InstallRoot 'runtime\snapshots'
$env:D4_RULEKIT_CHROMIUM_EXECUTABLE = Join-Path $InstallRoot 'runtime\chromium\chrome-win64\chrome.exe'
$env:D4PLANNER_WS_PORT_MODE = $(if ($WsPortMode -eq 'Dynamic') { 'DYNAMIC' } else { 'FIXED_APPROVED_UAT' })
if ($WsPortMode -eq 'FixedApprovedUat') {
    $env:D4PLANNER_APPROVED_UAT_PORT = [string]$ApprovedPort
} else {
    Remove-Item Env:D4PLANNER_APPROVED_UAT_PORT -ErrorAction SilentlyContinue
}
if ($EnableReadOnlyEquipmentRepository) {
    $env:D4PLANNER_EQUIPMENT_REPOSITORY_DB = $EquipmentRepositoryDb
    $env:D4PLANNER_CHARACTER_ID = $CharacterId
    $env:D4PLANNER_CHARACTER_DISPLAY_NAME = $CharacterDisplayName
} else {
    Remove-Item Env:D4PLANNER_EQUIPMENT_REPOSITORY_DB -ErrorAction SilentlyContinue
    Remove-Item Env:D4PLANNER_CHARACTER_ID -ErrorAction SilentlyContinue
    Remove-Item Env:D4PLANNER_CHARACTER_DISPLAY_NAME -ErrorAction SilentlyContinue
}
Remove-Item Env:D4PLANNER_EQUIPMENT_EVIDENCE_FILE -ErrorAction SilentlyContinue

$ownerState = Join-Path $privateRoot 'hud-owner.json'
try {
    $start = @{ FilePath = $frontend; WorkingDirectory = $InstallRoot; PassThru = $true }
    if ($SelfTest) { $start.ArgumentList = @('--self-test') }
    $process = Start-Process @start
    [ordered]@{
        schemaVersion = 'd4planner-hud-owner/v1'; pid = $process.Id
        executable = $frontend; startedAt = $process.StartTime.ToUniversalTime().ToString('o')
        installRoot = $InstallRoot; dataRoot = $DataRoot
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $ownerState -Encoding utf8NoBOM
    $process.WaitForExit()
    exit $process.ExitCode
}
finally {
    Remove-Item -LiteralPath $ownerState -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $bootstrap -Force -ErrorAction SilentlyContinue
}
