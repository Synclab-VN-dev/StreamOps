param(
    [Parameter(Position=0)]
    [ValidateSet('Doctor','Run','Build','Test','Smoke','Stop')]
    [string]$Action='Doctor'
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Project = Join-Path $Root 'utility\d4planner-overlay-poc'
$Exe = Join-Path $Project 'src-tauri\target\release\d4planner-overlay-poc.exe'

function Require([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing $Name. See utility/d4planner-overlay-poc/README.md"
    }
}
function Prepare-Dev {
    Require 'npm'
    Require 'cargo'
    Push-Location $Project
    try {
        if (-not (Test-Path 'node_modules')) {
            npm install --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
        }
        if (-not (Test-Path 'src-tauri\icons\icon.ico')) {
            npm run icon
            if ($LASTEXITCODE -ne 0) { throw 'Tauri icon generation failed' }
        }
    } finally { Pop-Location }
}

switch ($Action) {
    'Doctor' {
        Write-Host "Overlay project: $Project"
        foreach ($name in @('node','npm','cargo','rustc')) {
            $entry=Get-Command $name -ErrorAction SilentlyContinue
            if ($entry) { Write-Host "[OK] $name" }
            else { Write-Warning "[MISSING] $name" }
        }
        if (Test-Path $Exe) { Write-Host "[OK] EXE: $Exe" }
        else { Write-Host "[INFO] EXE not built. Download CI artifact or Build." }
    }
    'Run' {
        Prepare-Dev
        Push-Location $Project
        try {
            npm run tauri:dev
            if ($LASTEXITCODE -ne 0) { throw 'Tauri dev failed' }
        } finally { Pop-Location }
    }
    'Test' {
        Prepare-Dev
        Push-Location $Project
        try {
            npm test
            if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
        } finally { Pop-Location }
    }
    'Build' {
        Prepare-Dev
        Push-Location $Project
        try {
            npm run tauri:build
            if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed' }
            if (-not (Test-Path $Exe)) { throw "No EXE: $Exe" }
            Write-Host "[OK] $Exe"
        } finally { Pop-Location }
    }
    'Smoke' {
        & (Join-Path $Root 'scripts\e2e\d4-overlay-poc-smoke.ps1') -ExePath $Exe
    }
    'Stop' {
        $procs=@(Get-Process -Name 'd4planner-overlay-poc' -ErrorAction SilentlyContinue)
        foreach ($proc in $procs) {
            Write-Host "Stopping PID $($proc.Id)"
            Stop-Process -Id $proc.Id -ErrorAction Stop
        }
        if (-not $procs.Count) { Write-Host 'Overlay not running' }
    }
}
