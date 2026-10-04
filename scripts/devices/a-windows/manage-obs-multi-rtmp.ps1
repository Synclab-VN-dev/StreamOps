# Host-layer lifecycle for the issue #33 Multiple RTMP Outputs POC.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory)]
    [ValidateSet("Inspect", "Install", "Verify", "Rollback")]
    [string]$Action,
    [string]$EvidenceRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$releaseTag = "0.7.4.3"
$packageVersion = "0.7.4.0"
$artifactName = "obs-multi-rtmp-0.7.4.0-windows-x64.zip"
$artifactUrl = "https://github.com/sorayuki/obs-multi-rtmp/releases/download/$releaseTag/$artifactName"
$artifactSha256 = "5fc2a14a4222cef914d4703325853b1f97247abe76bbd1fccd0dbd40831affe5"
$expectedObsVersion = "32.2.1"
$expectedFileCount = 73
$obsExecutable = "C:\Program Files\obs-studio\bin\64bit\obs64.exe"
$pluginRoot = Join-Path $env:PROGRAMDATA "obs-studio\plugins\obs-multi-rtmp"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $EvidenceRoot = Join-Path $repoRoot ".streamops\issue-33"
}
elseif (-not [IO.Path]::IsPathRooted($EvidenceRoot)) {
    $EvidenceRoot = Join-Path $repoRoot $EvidenceRoot
}
$EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot)
$transactionPointer = Join-Path $EvidenceRoot "current-transaction.json"

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or newer is required. Run this script with pwsh.exe."
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-JsonFile([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $json = $Value | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required state file is missing: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Assert-ObsVersion {
    if (-not (Test-Path -LiteralPath $obsExecutable -PathType Leaf)) {
        throw "OBS executable was not found: $obsExecutable"
    }
    $version = (Get-Item -LiteralPath $obsExecutable).VersionInfo.ProductVersion
    if ($version -ne $expectedObsVersion) {
        throw "This POC is pinned to OBS $expectedObsVersion; found $version at $obsExecutable."
    }
    return $version
}

function Assert-ObsStopped {
    $running = @(Get-CimInstance Win32_Process -Filter "Name = 'obs64.exe'" -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        throw "OBS must be stopped through StreamOps before $Action. Running PID(s): $($running.ProcessId -join ', ')."
    }
}

function Get-PluginConfigMetadata {
    $profilesRoot = Join-Path $env:APPDATA "obs-studio\basic\profiles"
    if (-not (Test-Path -LiteralPath $profilesRoot -PathType Container)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $profilesRoot -Filter "obs-multi-rtmp.json" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName |
            ForEach-Object {
                [ordered]@{
                    path = $_.FullName
                    length = $_.Length
                    sha256 = Get-Sha256 $_.FullName
                    last_write_utc = $_.LastWriteTimeUtc.ToString("o")
                }
            }
    )
}

function Get-SceneCollectionMetadata {
    $scenesRoot = Join-Path $env:APPDATA "obs-studio\basic\scenes"
    if (-not (Test-Path -LiteralPath $scenesRoot -PathType Container)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $scenesRoot -Filter "*.json" -File -ErrorAction SilentlyContinue |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    name = $_.Name
                    length = $_.Length
                    sha256 = Get-Sha256 $_.FullName
                }
            }
    )
}

function Get-PluginFiles([string]$Root = $pluginRoot) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $Root -File -Recurse -Force |
            Sort-Object FullName |
            ForEach-Object {
                [ordered]@{
                    relative_path = [IO.Path]::GetRelativePath($Root, $_.FullName).Replace("\", "/")
                    length = $_.Length
                    sha256 = Get-Sha256 $_.FullName
                }
            }
    )
}

function Get-Inspection {
    $obsVersion = Assert-ObsVersion
    $obsProcesses = @(
        Get-CimInstance Win32_Process -Filter "Name = 'obs64.exe'" -ErrorAction SilentlyContinue |
            ForEach-Object {
                [ordered]@{
                    pid = $_.ProcessId
                    executable_path = $_.ExecutablePath
                    session_id = $_.SessionId
                    creation_date = if ($null -eq $_.CreationDate) { $null } else { $_.CreationDate.ToString("o") }
                }
            }
    )
    $knownRoots = @(
        "C:\Program Files\obs-studio\obs-plugins\64bit",
        "C:\Program Files\obs-studio\data\obs-plugins",
        (Join-Path $env:APPDATA "obs-studio\plugins"),
        (Join-Path $env:PROGRAMDATA "obs-studio\plugins")
    )
    $matches = @(
        $knownRoots |
            Where-Object { Test-Path -LiteralPath $_ -PathType Container } |
            ForEach-Object {
                Get-ChildItem -LiteralPath $_ -Recurse -Force -ErrorAction SilentlyContinue |
                    Where-Object { $_.FullName -match "(?i)(multi.?rtmp|multiple.?rtmp)" } |
                    ForEach-Object {
                        [ordered]@{
                            path = $_.FullName
                            is_directory = $_.PSIsContainer
                            length = if ($_.PSIsContainer) { $null } else { $_.Length }
                        }
                    }
            }
    )
    $globalIni = Join-Path $env:APPDATA "obs-studio\global.ini"
    return [ordered]@{
        captured_at = [DateTimeOffset]::Now.ToString("o")
        computer = $env:COMPUTERNAME
        obs = [ordered]@{
            executable = $obsExecutable
            version = $obsVersion
            processes = $obsProcesses
        }
        source = [ordered]@{
            release_tag = $releaseTag
            package_version = $packageVersion
            artifact_name = $artifactName
            artifact_url = $artifactUrl
            artifact_sha256 = $artifactSha256
        }
        install = [ordered]@{
            plugin_root = $pluginRoot
            plugin_files = Get-PluginFiles
            matching_paths = $matches
        }
        obs_state = [ordered]@{
            scene_collections = Get-SceneCollectionMetadata
            plugin_configs = Get-PluginConfigMetadata
            global_ini = if (Test-Path -LiteralPath $globalIni -PathType Leaf) {
                [ordered]@{ path = $globalIni; length = (Get-Item $globalIni).Length; sha256 = Get-Sha256 $globalIni }
            } else { $null }
        }
    }
}

function Test-ArchiveEntry([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name.EndsWith("/")) {
        return $false
    }
    if ([IO.Path]::IsPathRooted($Name) -or $Name -match "(^|/)\.\.(/|$)") {
        throw "Artifact contains an unsafe path: $Name"
    }
    return (
        $Name -in @(
            "obs-plugins/64bit/obs-multi-rtmp.dll",
            "obs-plugins/64bit/obs-multi-rtmp.pdb"
        ) -or
        $Name -match "^data/obs-plugins/obs-multi-rtmp/locale/[A-Za-z0-9-]+\.ini$"
    )
}

function Get-ValidatedArtifact {
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("StreamOps-issue33-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    try {
        $archivePath = Join-Path $tempRoot $artifactName
        Invoke-WebRequest -UseBasicParsing -Uri $artifactUrl -OutFile $archivePath
        $actualHash = Get-Sha256 $archivePath
        if ($actualHash -ne $artifactSha256) {
            throw "Artifact SHA-256 mismatch. Expected $artifactSha256, got $actualHash."
        }

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            $fileEntries = @($archive.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) })
            $unexpected = @($fileEntries | Where-Object { -not (Test-ArchiveEntry $_.FullName) })
            if ($unexpected.Count -gt 0) {
                throw "Artifact contains unexpected entries: $($unexpected.FullName -join ', ')"
            }
            if ($fileEntries.Count -ne $expectedFileCount) {
                throw "Artifact file count mismatch. Expected $expectedFileCount, got $($fileEntries.Count)."
            }
        }
        finally {
            $archive.Dispose()
        }

        $extractRoot = Join-Path $tempRoot "extracted"
        Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot
        $stageRoot = Join-Path $tempRoot "stage"
        $stageBin = Join-Path $stageRoot "bin\64bit"
        $stageData = Join-Path $stageRoot "data\locale"
        New-Item -ItemType Directory -Path $stageBin, $stageData -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $extractRoot "obs-plugins\64bit\obs-multi-rtmp.dll") -Destination $stageBin
        Copy-Item -LiteralPath (Join-Path $extractRoot "obs-plugins\64bit\obs-multi-rtmp.pdb") -Destination $stageBin
        Copy-Item -Path (Join-Path $extractRoot "data\obs-plugins\obs-multi-rtmp\locale\*.ini") -Destination $stageData
        $stagedFiles = @(Get-PluginFiles $stageRoot)
        if ($stagedFiles.Count -ne $expectedFileCount) {
            throw "Staged file count mismatch. Expected $expectedFileCount, got $($stagedFiles.Count)."
        }
        return [ordered]@{
            temp_root = $tempRoot
            stage_root = $stageRoot
            files = $stagedFiles
        }
    }
    catch {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
        throw
    }
}

function Assert-NoExistingPluginConfig {
    $configs = @(Get-PluginConfigMetadata)
    if ($configs.Count -gt 0) {
        throw "Existing obs-multi-rtmp profile configuration was found. Refusing to inspect or copy possible RTMP credentials: $($configs.path -join ', ')"
    }
}

function Invoke-Install {
    Assert-ObsStopped
    [void](Assert-ObsVersion)
    $artifact = Get-ValidatedArtifact
    try {
        $currentFiles = @(Get-PluginFiles)
        $currentErrors = @(Compare-FileManifest @($artifact.files) $currentFiles)
        if ($currentErrors.Count -eq 0 -and $currentFiles.Count -eq $expectedFileCount) {
            [ordered]@{
                action = "Install"
                result = "already_installed"
                release_tag = $releaseTag
                package_version = $packageVersion
                plugin_root = $pluginRoot
                file_count = $currentFiles.Count
            } | ConvertTo-Json -Depth 6
            return
        }
        Assert-NoExistingPluginConfig
        if (-not $PSCmdlet.ShouldProcess($pluginRoot, "Install pinned obs-multi-rtmp $releaseTag ($expectedFileCount files)")) {
            [ordered]@{ action = "Install"; what_if = $true; plugin_root = $pluginRoot; files = $artifact.files } |
                ConvertTo-Json -Depth 8
            return
        }

        $timestamp = (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
        $transactionRoot = Join-Path $EvidenceRoot "transactions\$timestamp"
        $backupRoot = Join-Path $transactionRoot "backup\obs-multi-rtmp"
        New-Item -ItemType Directory -Path $transactionRoot -Force | Out-Null
        $baseline = Get-Inspection
        $pluginExisted = Test-Path -LiteralPath $pluginRoot -PathType Container
        if ($pluginExisted) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $backupRoot) -Force | Out-Null
            Copy-Item -LiteralPath $pluginRoot -Destination $backupRoot -Recurse
        }

        $transaction = [ordered]@{
            state = "pending"
            created_at = [DateTimeOffset]::Now.ToString("o")
            transaction_root = $transactionRoot
            release_tag = $releaseTag
            package_version = $packageVersion
            artifact_url = $artifactUrl
            artifact_sha256 = $artifactSha256
            plugin_root = $pluginRoot
            plugin_existed = $pluginExisted
            backup_root = if ($pluginExisted) { $backupRoot } else { $null }
            baseline_plugin_configs = $baseline.obs_state.plugin_configs
            baseline_scene_collections = $baseline.obs_state.scene_collections
            expected_files = $artifact.files
        }
        Write-JsonFile (Join-Path $transactionRoot "baseline.json") $baseline
        Write-JsonFile (Join-Path $transactionRoot "transaction.json") $transaction
        Write-JsonFile $transactionPointer ([ordered]@{ transaction_path = (Join-Path $transactionRoot "transaction.json") })

        if (Test-Path -LiteralPath $pluginRoot) {
            Remove-Item -LiteralPath $pluginRoot -Recurse -Force
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $pluginRoot) -Force | Out-Null
        Copy-Item -LiteralPath $artifact.stage_root -Destination $pluginRoot -Recurse

        $installedFiles = @(Get-PluginFiles)
        if ($installedFiles.Count -ne $expectedFileCount) {
            throw "Installed file count mismatch. Expected $expectedFileCount, got $($installedFiles.Count). Use Rollback."
        }
        $transaction.state = "installed"
        $transaction.installed_at = [DateTimeOffset]::Now.ToString("o")
        $transaction.installed_files = $installedFiles
        Write-JsonFile (Join-Path $transactionRoot "transaction.json") $transaction
        [ordered]@{
            action = "Install"
            result = "installed"
            release_tag = $releaseTag
            package_version = $packageVersion
            plugin_root = $pluginRoot
            file_count = $installedFiles.Count
            transaction = Join-Path $transactionRoot "transaction.json"
        } | ConvertTo-Json -Depth 6
    }
    finally {
        if ($null -ne $artifact -and (Test-Path -LiteralPath $artifact.temp_root)) {
            Remove-Item -LiteralPath $artifact.temp_root -Recurse -Force
        }
    }
}

function Compare-FileManifest([object[]]$Expected, [object[]]$Actual) {
    $expectedByPath = @{}
    foreach ($file in $Expected) { $expectedByPath[[string]$file.relative_path] = $file }
    $actualByPath = @{}
    foreach ($file in $Actual) { $actualByPath[[string]$file.relative_path] = $file }
    $errors = [Collections.Generic.List[string]]::new()
    foreach ($path in $expectedByPath.Keys) {
        if (-not $actualByPath.ContainsKey($path)) {
            $errors.Add("missing: $path")
        }
        elseif ($actualByPath[$path].sha256 -ne $expectedByPath[$path].sha256) {
            $errors.Add("hash mismatch: $path")
        }
    }
    foreach ($path in $actualByPath.Keys) {
        if (-not $expectedByPath.ContainsKey($path)) {
            $errors.Add("unexpected: $path")
        }
    }
    return @($errors)
}

function Get-CurrentTransaction {
    $pointer = Read-JsonFile $transactionPointer
    return Read-JsonFile ([string]$pointer.transaction_path)
}

function Invoke-Verify {
    $obsVersion = Assert-ObsVersion
    $transaction = Get-CurrentTransaction
    $actualFiles = @(Get-PluginFiles)
    $expectedFiles = @($transaction.expected_files)
    $errors = @(Compare-FileManifest $expectedFiles $actualFiles)
    $latestLog = Get-ChildItem -LiteralPath (Join-Path $env:APPDATA "obs-studio\logs") -Filter "*.txt" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    $loadLines = @()
    $moduleListed = $false
    if ($null -ne $latestLog) {
        $loadLines = @(
            Select-String -LiteralPath $latestLog.FullName -Pattern "\[obs-multi-rtmp\] version:" -CaseSensitive:$false |
                Select-Object -Last 3 |
                ForEach-Object { $_.Line }
        )
        $moduleListed = $null -ne (Select-String -LiteralPath $latestLog.FullName -Pattern "^\s+obs-multi-rtmp\.dll\s*$" -CaseSensitive:$false | Select-Object -First 1)
    }
    $result = [ordered]@{
        action = "Verify"
        obs_version = $obsVersion
        obs_running = @(Get-Process -Name "obs64" -ErrorAction SilentlyContinue).Count -gt 0
        plugin_root = $pluginRoot
        expected_file_count = $expectedFiles.Count
        actual_file_count = $actualFiles.Count
        files_valid = $errors.Count -eq 0
        file_errors = $errors
        latest_obs_log = if ($null -eq $latestLog) { $null } else { $latestLog.FullName }
        plugin_load_lines = $loadLines
        module_listed = $moduleListed
        profile_configs = Get-PluginConfigMetadata
    }
    $result | ConvertTo-Json -Depth 8
    if ($errors.Count -gt 0) {
        throw "Installed plugin files do not match the pinned artifact: $($errors -join '; ')"
    }
}

function Test-EmptyPluginConfig([string]$Path) {
    try {
        $config = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        $allowedNames = @("audio_configs", "targets", "video_configs")
        $names = @($config.PSObject.Properties.Name)
        if (@($names | Where-Object { $_ -notin $allowedNames }).Count -gt 0) { return $false }
        foreach ($name in $allowedNames) {
            if ($name -notin $names -or @($config.$name).Count -ne 0) { return $false }
        }
        return $true
    }
    catch {
        return $false
    }
}

function Invoke-Rollback {
    Assert-ObsStopped
    $transaction = Get-CurrentTransaction
    $actualFiles = @(Get-PluginFiles)
    $expectedFiles = @($transaction.expected_files)
    $expectedByPath = @{}
    foreach ($file in $expectedFiles) { $expectedByPath[[string]$file.relative_path] = $file }
    foreach ($file in $actualFiles) {
        if (-not $expectedByPath.ContainsKey([string]$file.relative_path)) {
            throw "Rollback refused because the plugin directory contains an unmanaged file: $($file.relative_path)"
        }
        if ($file.sha256 -ne $expectedByPath[[string]$file.relative_path].sha256) {
            throw "Rollback refused because an installed file changed: $($file.relative_path)"
        }
    }

    $baselineConfigPaths = @($transaction.baseline_plugin_configs | ForEach-Object { [string]$_.path })
    $newEmptyConfigs = [Collections.Generic.List[string]]::new()
    foreach ($config in @(Get-PluginConfigMetadata)) {
        if ($config.path -notin $baselineConfigPaths) {
            if (-not (Test-EmptyPluginConfig ([string]$config.path))) {
                throw "Rollback refused because a new obs-multi-rtmp config is not empty: $($config.path)"
            }
            $newEmptyConfigs.Add([string]$config.path)
        }
    }

    if (-not $PSCmdlet.ShouldProcess($pluginRoot, "Rollback obs-multi-rtmp and restore the pre-install plugin state")) {
        [ordered]@{
            action = "Rollback"
            what_if = $true
            plugin_root = $pluginRoot
            files_to_remove = $actualFiles.relative_path
            empty_profile_configs_to_remove = @($newEmptyConfigs)
            backup_to_restore = $transaction.backup_root
        } | ConvertTo-Json -Depth 8
        return
    }

    if (Test-Path -LiteralPath $pluginRoot) {
        Remove-Item -LiteralPath $pluginRoot -Recurse -Force
    }
    if ([bool]$transaction.plugin_existed) {
        if ([string]::IsNullOrWhiteSpace([string]$transaction.backup_root) -or
            -not (Test-Path -LiteralPath ([string]$transaction.backup_root) -PathType Container)) {
            throw "Rollback backup is missing: $($transaction.backup_root)"
        }
        Copy-Item -LiteralPath ([string]$transaction.backup_root) -Destination $pluginRoot -Recurse
    }
    foreach ($path in $newEmptyConfigs) {
        Remove-Item -LiteralPath $path -Force
    }
    $transaction.state = "rolled_back"
    $transaction.rolled_back_at = [DateTimeOffset]::Now.ToString("o")
    Write-JsonFile (Join-Path ([string]$transaction.transaction_root) "transaction.json") $transaction
    [ordered]@{
        action = "Rollback"
        result = "rolled_back"
        plugin_root = $pluginRoot
        restored_previous_plugin = [bool]$transaction.plugin_existed
        removed_empty_profile_configs = @($newEmptyConfigs)
    } | ConvertTo-Json -Depth 8
}

switch ($Action) {
    "Inspect" { Get-Inspection | ConvertTo-Json -Depth 12 }
    "Install" { Invoke-Install }
    "Verify" { Invoke-Verify }
    "Rollback" { Invoke-Rollback }
}
