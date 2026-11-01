param(
    [Parameter(Mandatory=$true)][string]$Root,
    [string]$Python = 'python',
    [switch]$CheckOnly,
    [switch]$SetupOnly,
    [switch]$Rebuild,
    [string]$SourceHead,
    [string]$Version,
    [string]$SourceSha256
)
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($Root)
if ((Split-Path $rootPath -Leaf) -notmatch '^d4planner-build-[0-9a-f]{32}$') {
    throw 'Expected a dedicated wrapper run directory'
}
$process = Get-Process -Id $PID
@{pid=$PID; started=$process.StartTime.ToUniversalTime().Ticks.ToString()} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $rootPath 'owner.json') -Encoding UTF8
. (Join-Path $PSScriptRoot 'setup_build_vm.ps1') -CheckOnly:$CheckOnly
$Python=$pythonBase
if ($SetupOnly) { exit 0 }

function Get-Preflight {
    $errors = [Collections.Generic.List[string]]::new()
    $versions = @{}
    if ($env:OS -ne 'Windows_NT') {
        return @{ready=$false; versions=$versions; errors=@('Windows VM required')}
    }
    $rustReady = $false
    if (Get-Command rustup -ErrorAction SilentlyContinue) {
        $installed = & rustup toolchain list
        $rustReady = [bool]($installed -match '^1\.90\.0-')
    }
    foreach ($entry in @(@('python',$Python,'Python 3.12.10'),
                         @('node','node','v22.22.1'), @('git','git','git version'),
                         @('rust','rustc','rustc 1.90.0'))) {
        if ($entry[0] -eq 'rust' -and -not $rustReady) {
            $errors.Add('Missing installed Rust 1.90.0 toolchain; preflight will not install it')
            continue
        }
        if (-not (Get-Command $entry[1] -ErrorAction SilentlyContinue)) {
            $errors.Add("Missing $($entry[0]) executable: $($entry[1])")
            continue
        }
        try {
            $ErrorActionPreference = 'Continue'
            $text = (& $entry[1] --version 2>&1 | Out-String).Trim()
            $code = $LASTEXITCODE
            $ErrorActionPreference = 'Stop'
            $versions[$entry[0]] = $text
            $matches = if ($entry[0] -in @('python','node')) { $text -eq $entry[2] }
                       else { $text.StartsWith($entry[2]+' ') }
            if ($code -ne 0 -or -not $matches) {
                $errors.Add("Required $($entry[2]); got $text")
            }
        } catch { $errors.Add("Missing $($entry[0]): $($_.Exception.Message)") }
    }
    foreach ($tool in @('npm.cmd','cargo','rustup')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { $errors.Add("Missing $tool") }
    }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { $errors.Add('Missing Visual Studio Build Tools / vswhere') }
    else {
        $vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if (-not $vs) { $errors.Add('Missing MSVC x64 C++ Build Tools (Windows SDK also required)') }
    }
    return @{ready=($errors.Count -eq 0); versions=$versions; errors=@($errors)}
}

if ($CheckOnly) {
    $check = Get-Preflight
    $check | ConvertTo-Json -Depth 5
    if (-not $check.ready) { exit 1 }
    exit 0
}

$env:CARGO_BUILD_JOBS='2'
$env:D4_LOCAL_RUNTIME_CACHE='C:\D4Builder\frameworks\public-runtimes'
function Initialize-BuildCache([string]$CacheRoot, [switch]$Clean) {
    # Caller supplies the dedicated builder cache root, never a source/user path.
    $target=Join-Path $CacheRoot 'cargo-target'
    if ($Clean -and (Test-Path -LiteralPath $target)) {
        if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing to clear redirected compilation cache' }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    return $target
}
$env:CARGO_TARGET_DIR=Initialize-BuildCache 'C:\D4Builder\cache' -Clean:$Rebuild


$log = Join-Path $rootPath 'build.log'
$resultPath = Join-Path $rootPath 'result.json'
$script:buildExit = 1
$result = @{exitCode=1; sourceHead=$SourceHead; version=$Version; files=@{}; error=$null}
'' | Set-Content -LiteralPath $log -Encoding UTF8

function Invoke-Native([string]$Program, [string[]]$Argv) {
    # PS5 treats native stderr as ErrorRecord. Compiler warnings are not failure;
    # use the native exit code, while preserving both streams in the build log.
    Get-Command $Program -ErrorAction Stop | Out-Null
    $writer = [IO.StreamWriter]::new($log, $true, [Text.UTF8Encoding]::new($false))
    $writer.AutoFlush = $true
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Program @Argv 2>&1 | ForEach-Object {
            $line = $_.ToString()
            $writer.WriteLine($line)
            [Console]::WriteLine($line)
        }
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $saved; $writer.Dispose() }
    if ($code -ne 0) {
        $script:buildExit = $code
        throw "Native command failed: $Program (exit $code)"
    }
}

try {
    if ($SourceHead -notmatch '^[0-9a-f]{40}$' -or $SourceSha256 -notmatch '^[0-9a-f]{64}$' -or
        $Version -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
        throw 'Invalid source/version/archive identity'
    }
    $check = Get-Preflight
    if (-not $check.ready) { throw ($check.errors -join '; ') }
    $archive = Join-Path $rootPath 'source.zip'
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceSha256) {
        throw 'Source archive checksum mismatch'
    }
    $source = Join-Path $rootPath 'source'
    if (Test-Path $source) { throw 'Source directory already exists; refusing to reuse a run' }
    Expand-Archive -LiteralPath $archive -DestinationPath $source
    Set-Location $source
    $actualHead = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualHead -ne $SourceHead) { throw 'Git HEAD mismatch' }
    $env:GIT_CONFIG_GLOBAL = Join-Path $rootPath 'empty-git-config'
    '' | Set-Content -LiteralPath $env:GIT_CONFIG_GLOBAL
    Invoke-Native git @('config','core.autocrlf','false')
    $temp = Join-Path $rootPath 'temp'
    New-Item -ItemType Directory -Path $temp | Out-Null
    $env:TEMP = $temp; $env:TMP = $temp
    $env:D4_BUILD_ONLY = 'true'
    $env:GITHUB_OUTPUT = Join-Path $rootPath 'github-output.txt'
    # Reconstruct public inputs using the pins, not inherited private URL secrets.
    Remove-Item Env:D4_PUBLIC_RUNTIME_INPUT_URL -ErrorAction SilentlyContinue
    Remove-Item Env:D4_PUBLIC_RUNTIME_INPUT_SHA256 -ErrorAction SilentlyContinue
    $venv = Join-Path $rootPath 'venv'
    Invoke-Native $Python @('-m','venv',$venv)
    $pythonBuild = Join-Path $venv 'Scripts\python.exe'
    $env:PATH = (Join-Path $venv 'Scripts')+';'+$env:PATH
    Invoke-Native $pythonBuild @('-m','pip','install','setuptools==80.9.0','wheel==0.45.1','pytest==9.1.1',
        '-r','utility/d4planner/d4planner-be/release1/requirements-release.txt')
    $tool = 'utility/d4planner/d4planner-be/tools/release_ci.py'
    $out = Join-Path $rootPath 'out'
    $common = @('--channel','stable','--version',$Version,'--source',$SourceHead,'--directory',$out)
    Invoke-Native $pythonBuild (@($tool,'validate')+$common)
    Invoke-Native $pythonBuild (@($tool,'build')+$common)
    $artifact = Join-Path $out 'build\verified-artifact'
    $meta = Get-Content -LiteralPath (Join-Path $artifact 'release-metadata.json') -Raw | ConvertFrom-Json
    $env:D4_BUILT_SETUP_SHA256 = $meta.sha256
    $verifyArgs = @('--channel','stable','--version',$Version,'--source',$SourceHead,'--directory',$artifact)
    Invoke-Native $pythonBuild (@($tool,'prepare-upload')+$verifyArgs)
    Invoke-Native $pythonBuild (@($tool,'validate-upload')+$verifyArgs)
    foreach ($name in @("D4Planner-Setup-$Version.exe",'release-metadata.json','SHA256SUMS','UAT.md')) {
        $result.files[$name] = (Get-FileHash -LiteralPath (Join-Path $artifact $name) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $script:buildExit = 0
} catch {
    $result.error = $_.Exception.Message
    Add-Content -LiteralPath $log -Value $result.error
} finally {
    $result.exitCode = $script:buildExit
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding UTF8
}
exit $script:buildExit
