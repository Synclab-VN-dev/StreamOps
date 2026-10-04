# Host-layer lifecycle for the issue #33 Multiple RTMP Outputs POC.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory)]
    [ValidateSet("Inspect", "Status", "Install", "Verify", "Rollback")]
    [string]$Action,
    [string]$EvidenceRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$desiredState = Get-Content -LiteralPath (Join-Path $PSScriptRoot "obs-multi-rtmp-manifest.json") -Raw | ConvertFrom-Json
$releaseTag = [string]$desiredState.release_tag
$packageVersion = [string]$desiredState.package_version
$artifactName = [string]$desiredState.artifact_name
$artifactUrl = [string]$desiredState.artifact_url
$artifactSha256 = [string]$desiredState.artifact_sha256
$expectedObsVersion = [string]$desiredState.expected_obs_version
$expectedFileCount = [int]$desiredState.file_count
$expectedTreeSha256 = [string]$desiredState.tree_sha256
$expectedRelativePaths = @($desiredState.relative_paths | ForEach-Object { [string]$_ })
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

function Get-TreeSha256([object[]]$Files) {
    $lines = @(
        $Files | Sort-Object relative_path | ForEach-Object {
            "$($_.relative_path)|$($_.length)|$($_.sha256)"
        }
    )
    $bytes = [Text.Encoding]::UTF8.GetBytes([string]::Join("`n", $lines))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Get-InstallState {
    $files = @(Get-PluginFiles)
    if ($files.Count -eq 0 -and -not (Test-Path -LiteralPath $pluginRoot)) {
        return [ordered]@{ installation = "absent"; files = $files }
    }
    $paths = @($files | ForEach-Object { [string]$_.relative_path })
    $exactPaths = $paths.Count -eq $expectedFileCount -and
        @($paths | Where-Object { $_ -notin $expectedRelativePaths }).Count -eq 0 -and
        @($expectedRelativePaths | Where-Object { $_ -notin $paths }).Count -eq 0
    $exact = $exactPaths -and (Get-TreeSha256 $files) -eq $expectedTreeSha256
    return [ordered]@{ installation = if ($exact) { "exact" } else { "conflict" }; files = $files }
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
        throw "incompatible_obs: expected OBS $expectedObsVersion"
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
        $stagedPaths = @($stagedFiles | ForEach-Object { [string]$_.relative_path })
        if (@($stagedPaths | Where-Object { $_ -notin $expectedRelativePaths }).Count -gt 0 -or
            @($expectedRelativePaths | Where-Object { $_ -notin $stagedPaths }).Count -gt 0 -or
            (Get-TreeSha256 $stagedFiles) -ne $expectedTreeSha256) {
            throw "Artifact contents do not match the pinned desired-state manifest."
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

function Invoke-Install {
    [void](Assert-ObsVersion)
    $currentState = Get-InstallState
    if ($currentState.installation -eq "exact") {
        [ordered]@{
            ok = $true
            action = "Install"
            result = "already_installed"
            release_tag = $releaseTag
            package_version = $packageVersion
            file_count = @($currentState.files).Count
        }
        return
    }
    Assert-ObsStopped
    if ($WhatIfPreference) {
        [void]$PSCmdlet.ShouldProcess($pluginRoot, "Install pinned obs-multi-rtmp $releaseTag ($expectedFileCount files)")
        [ordered]@{
            action = "Install"
            what_if = $true
            release_tag = $releaseTag
            package_version = $packageVersion
            artifact_url = $artifactUrl
            artifact_sha256 = $artifactSha256
            expected_file_count = $expectedFileCount
        }
        return
    }
    $artifact = Get-ValidatedArtifact
    $transaction = $null
    try {
        if (-not $PSCmdlet.ShouldProcess($pluginRoot, "Install pinned obs-multi-rtmp $releaseTag ($expectedFileCount files)")) {
            [ordered]@{ ok = $true; action = "Install"; what_if = $true; file_count = @($artifact.files).Count }
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
            ok = $true
            action = "Install"
            result = "installed"
            release_tag = $releaseTag
            package_version = $packageVersion
            file_count = $installedFiles.Count
        }
    }
    catch {
        if ($null -ne $transaction) {
            try {
                if (Test-Path -LiteralPath $pluginRoot) {
                    Remove-Item -LiteralPath $pluginRoot -Recurse -Force
                }
                if ([bool]$transaction.plugin_existed -and
                    (Test-Path -LiteralPath ([string]$transaction.backup_root) -PathType Container)) {
                    Copy-Item -LiteralPath ([string]$transaction.backup_root) -Destination $pluginRoot -Recurse
                }
                $transaction.state = "failed_restored"
                $transaction | Add-Member -NotePropertyName "failed_at" `
                    -NotePropertyValue ([DateTimeOffset]::Now.ToString("o")) -Force
                Write-JsonFile (Join-Path ([string]$transaction.transaction_root) "transaction.json") $transaction
            }
            catch {
                # Preserve the original install failure; status will expose any remaining conflict.
            }
        }
        throw
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

function Get-LoadEvidence {
    $processes = @(
        Get-CimInstance Win32_Process -Filter "Name = 'obs64.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -eq $obsExecutable }
    )
    if ($processes.Count -ne 1) {
        return [ordered]@{ obs_running = $false; loaded = $false; loaded_version = $null }
    }
    $startedUtc = $processes[0].CreationDate.ToUniversalTime()
    $latestLog = Get-ChildItem -LiteralPath (Join-Path $env:APPDATA "obs-studio\logs") -Filter "*.txt" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.CreationTimeUtc -ge $startedUtc.AddSeconds(-5) } |
        Sort-Object CreationTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latestLog) {
        return [ordered]@{ obs_running = $true; loaded = $false; loaded_version = $null }
    }
    $versionMatch = Select-String -LiteralPath $latestLog.FullName `
        -Pattern "\[obs-multi-rtmp\] version:\s*([0-9.]+)" -CaseSensitive:$false |
        Select-Object -Last 1
    $moduleListed = $null -ne (Select-String -LiteralPath $latestLog.FullName `
        -Pattern "obs-multi-rtmp\.dll\s*$" -CaseSensitive:$false | Select-Object -First 1)
    $loadedVersion = if ($null -eq $versionMatch) { $null } else { $versionMatch.Matches[0].Groups[1].Value }
    return [ordered]@{
        obs_running = $true
        loaded = $moduleListed -and $loadedVersion -eq $packageVersion
        loaded_version = $loadedVersion
    }
}

function Get-SafeStatus {
    $foundVersion = if (Test-Path -LiteralPath $obsExecutable -PathType Leaf) {
        (Get-Item -LiteralPath $obsExecutable).VersionInfo.ProductVersion
    } else { $null }
    $install = Get-InstallState
    $load = Get-LoadEvidence
    return [ordered]@{
        ok = $true
        action = "Status"
        installation = $install.installation
        compatible = $foundVersion -eq $expectedObsVersion
        loaded = [bool]$load.loaded
        loaded_version = $load.loaded_version
    }
}

function Invoke-Verify {
    [void](Assert-ObsVersion)
    $install = Get-InstallState
    if ($install.installation -ne "exact") { throw "manifest_mismatch: installed plugin files do not match desired state" }
    $load = Get-LoadEvidence
    if (-not $load.obs_running) { throw "obs_not_running: OBS is not running" }
    if ([string]::IsNullOrWhiteSpace([string]$load.loaded_version)) { throw "version_not_loaded: plugin version evidence is missing" }
    if (-not $load.loaded) { throw "module_not_loaded: the exact plugin module/version is not loaded" }
    return [ordered]@{
        ok = $true
        action = "Verify"
        installation = "exact"
        compatible = $true
        loaded = $true
        loaded_version = [string]$load.loaded_version
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
    $manifestErrors = @(Compare-FileManifest $expectedFiles $actualFiles)
    if ($manifestErrors.Count -gt 0) {
        throw "rollback_conflict: installed plugin files are missing, modified, or unmanaged"
    }
    $expectedByPath = @{}
    foreach ($file in $expectedFiles) { $expectedByPath[[string]$file.relative_path] = $file }
    foreach ($file in $actualFiles) {
        if (-not $expectedByPath.ContainsKey([string]$file.relative_path)) {
            throw "rollback_conflict: plugin directory contains an unmanaged file"
        }
        if ($file.sha256 -ne $expectedByPath[[string]$file.relative_path].sha256) {
            throw "rollback_conflict: an installed file changed"
        }
    }

    $baselineConfigPaths = @(
        $transaction.baseline_plugin_configs |
            Where-Object { $null -ne $_ -and $null -ne $_.PSObject.Properties["path"] } |
            ForEach-Object { [string]$_.path }
    )
    $newEmptyConfigs = [Collections.Generic.List[string]]::new()
    foreach ($config in @(Get-PluginConfigMetadata)) {
        if ($config.path -notin $baselineConfigPaths) {
            if (-not (Test-EmptyPluginConfig ([string]$config.path))) {
                throw "config_conflict: a new plugin config is not empty"
            }
            $newEmptyConfigs.Add([string]$config.path)
        }
    }

    if (-not $PSCmdlet.ShouldProcess($pluginRoot, "Rollback obs-multi-rtmp and restore the pre-install plugin state")) {
        [ordered]@{
            ok = $true
            action = "Rollback"
            what_if = $true
            file_count = $actualFiles.Count
        }
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
    $transaction | Add-Member -NotePropertyName "rolled_back_at" `
        -NotePropertyValue ([DateTimeOffset]::Now.ToString("o")) -Force
    Write-JsonFile (Join-Path ([string]$transaction.transaction_root) "transaction.json") $transaction
    [ordered]@{
        ok = $true
        action = "Rollback"
        result = "rolled_back"
        restored_previous_plugin = [bool]$transaction.plugin_existed
        removed_empty_profile_config_count = $newEmptyConfigs.Count
    }
}

try {
    $result = switch ($Action) {
        "Inspect" { Get-Inspection }
        "Status" { Get-SafeStatus }
        "Install" { Invoke-Install }
        "Verify" { Invoke-Verify }
        "Rollback" { Invoke-Rollback }
    }
    $result | ConvertTo-Json -Depth 12 -Compress
}
catch {
    $message = [string]$_.Exception.Message
    $code = if ($_.Exception -is [UnauthorizedAccessException] -or $_.Exception -is [Security.SecurityException]) {
        "permission_denied"
    } elseif ($message -match "^([a-z_]+):") {
        $Matches[1]
    } elseif ($message -match "OBS .*found") {
        "incompatible_obs"
    } elseif ($message -match "transaction|state file") {
        "transaction_missing"
    } elseif ($Action -eq "Install") {
        "install_failed"
    } elseif ($Action -eq "Verify") {
        "verify_failed"
    } elseif ($Action -eq "Rollback") {
        "rollback_failed"
    } else {
        "status_failed"
    }
    [ordered]@{ ok = $false; error = [ordered]@{ code = $code } } |
        ConvertTo-Json -Depth 4 -Compress
    exit 1
}
