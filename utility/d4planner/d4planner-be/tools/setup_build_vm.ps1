param([string]$StateRoot='C:\D4Builder', [switch]$CheckOnly)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$lock=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'vm-toolchain-lock.json') -Raw | ConvertFrom-Json
$frameworks=Join-Path $StateRoot 'frameworks'
$downloads=Join-Path $StateRoot 'downloads'
foreach($folder in @($StateRoot,$frameworks,$downloads)){New-Item -ItemType Directory -Force $folder | Out-Null}
$builderLock=[IO.File]::Open((Join-Path $StateRoot 'active-build.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$env:CARGO_HOME=Join-Path $frameworks 'cargo'
$env:RUSTUP_HOME=Join-Path $frameworks 'rustup'
$env:RUSTUP_TOOLCHAIN=$lock.rustToolchain
$pythonBase=Join-Path $frameworks 'python\python.exe'
$nodeRoot=Join-Path $frameworks ('node\'+$lock.node.prefix)
$gitRoot=Join-Path $frameworks 'git'
$gitVersion='git version '+($lock.git.version -replace '\.(\d+)$','.windows.$1')
$env:PATH="$frameworks\python;$frameworks\python\Scripts;$nodeRoot;$gitRoot\cmd;$env:CARGO_HOME\bin;"+$env:PATH
$env:PIP_CACHE_DIR=Join-Path $StateRoot 'cache\pip'
$env:npm_config_cache=Join-Path $StateRoot 'cache\npm'

function Get-BuilderDownload($spec) {
    $path=Join-Path $downloads $spec.file
    if(Test-Path $path){
        if((Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $spec.sha256){return $path}
        Remove-Item -LiteralPath $path
    }
    [Console]::WriteLine("SETUP download $($spec.file)")
    Invoke-WebRequest -UseBasicParsing -Uri $spec.url -OutFile ($path+'.partial')
    if((Get-FileHash ($path+'.partial') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.sha256){throw "Installer checksum mismatch: $($spec.file)"}
    Move-Item -LiteralPath ($path+'.partial') -Destination $path
    return $path
}
function Invoke-BuilderInstaller([string]$Exe,[string[]]$Arguments) {
    $p=Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru
    $handle=$p.Handle
    if(-not $p.WaitForExit(3600000)){
        & taskkill.exe /PID $p.Id /T /F | Out-Null
        throw 'Framework installer timed out'
    }
    if($p.ExitCode -notin @(0,3010)){throw "Framework installer failed with exit $($p.ExitCode): $Exe"}
    if($p.ExitCode -eq 3010){[Console]::WriteLine('SETUP installer requested a reboot; validation will determine readiness')}
}
function Test-BuilderVersion([string]$Exe,[string]$Expected) {
    if(-not (Test-Path $Exe)){return $false}
    $value=(& $Exe --version 2>$null | Out-String).Trim()
    return ($LASTEXITCODE -eq 0 -and $value -eq $Expected)
}
# The Python installer reuses an existing per-user registration. Reuse only an
# exact verified full interpreter rather than repeatedly attempting relocation.
if (-not(Test-BuilderVersion $pythonBase ('Python '+$lock.python.version))) {
    $registered=Get-ItemProperty 'HKCU:\Software\Python\PythonCore\3.12\InstallPath' -ErrorAction SilentlyContinue
    if ($registered -and (Test-BuilderVersion $registered.ExecutablePath ('Python '+$lock.python.version))) {
        $pythonBase=$registered.ExecutablePath
        $env:PATH=(Split-Path $pythonBase)+';'+$env:PATH
    }
}
$missing=[Collections.Generic.List[string]]::new()
if(-not (Test-BuilderVersion $pythonBase ('Python '+$lock.python.version))){
    if($CheckOnly){$missing.Add('Python')}else{
        [Console]::WriteLine('SETUP installing Python')
        Invoke-BuilderInstaller (Get-BuilderDownload $lock.python) @('/quiet','InstallAllUsers=0','Include_launcher=0','Include_test=0','PrependPath=0',"TargetDir=$frameworks\python")
    }
}
if(-not (Test-BuilderVersion (Join-Path $nodeRoot 'node.exe') ('v'+$lock.node.version))){
    if($CheckOnly){$missing.Add('Node')}else{
        [Console]::WriteLine('SETUP installing Node/npm')
        Expand-Archive -LiteralPath (Get-BuilderDownload $lock.node) -DestinationPath (Join-Path $frameworks 'node') -Force
    }
}
if(-not (Test-BuilderVersion (Join-Path $gitRoot 'cmd\git.exe') $gitVersion)){
    if($CheckOnly){$missing.Add('Git')}else{
        [Console]::WriteLine('SETUP installing Git')
        Expand-Archive -LiteralPath (Get-BuilderDownload $lock.git) -DestinationPath $gitRoot -Force
    }
}
$vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vc=$null
if(Test-Path $vswhere){$vc=& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 Microsoft.VisualStudio.Component.Windows11SDK.26100 -property installationPath}
if(-not $vc){
    if($CheckOnly){$missing.Add('MSVC/Windows SDK')}else{
        [Console]::WriteLine('SETUP installing MSVC C++ and Windows SDK (first setup only)')
        $isAdmin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        if(-not $isAdmin){throw 'VM build account needs elevation for first MSVC installation'}
        Invoke-BuilderInstaller (Get-BuilderDownload $lock.msvc) @('--quiet','--wait','--norestart','--nocache','--installPath',"$frameworks\msvc",'--add','Microsoft.VisualStudio.Workload.VCTools','--add','Microsoft.VisualStudio.Component.Windows11SDK.26100','--includeRecommended')
    }
}
$rustup=Join-Path $env:CARGO_HOME 'bin\rustup.exe'
$rustReady=$false
if(Test-Path $rustup){$rustReady=[bool]((& $rustup toolchain list) -match ('^'+[regex]::Escape($lock.rustToolchain)))}
if(-not $rustReady){
    if($CheckOnly){$missing.Add('Rust')}else{
        [Console]::WriteLine('SETUP installing pinned Rust')
        if(-not(Test-Path $rustup)){
            Invoke-BuilderInstaller (Get-BuilderDownload $lock.rustup) @('-y','--no-modify-path','--profile','minimal','--default-toolchain',$lock.rustToolchain)
        }else{
            & $rustup toolchain install $lock.rustToolchain --profile minimal
            if($LASTEXITCODE -ne 0){throw 'Rust toolchain installation failed'}
        }
    }
}
if($missing.Count){throw ('Missing frameworks: '+($missing -join ', '))}
if(-not(Test-BuilderVersion $pythonBase ('Python '+$lock.python.version))){throw 'Python verification failed'}
if(-not(Test-BuilderVersion (Join-Path $nodeRoot 'node.exe') ('v'+$lock.node.version))){throw 'Node verification failed'}
& "$gitRoot\cmd\git.exe" --version
if(-not(Test-BuilderVersion (Join-Path $gitRoot 'cmd\git.exe') $gitVersion)){throw 'Git verification failed'}
& "$env:CARGO_HOME\bin\rustc.exe" --version
if($LASTEXITCODE -ne 0){throw 'Rust verification failed'}
$vc=& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 Microsoft.VisualStudio.Component.Windows11SDK.26100 -property installationPath
if(-not $vc){throw 'MSVC/SDK verification failed'}
[Console]::WriteLine('SETUP_READY')
