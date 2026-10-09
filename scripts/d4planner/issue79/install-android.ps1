param([string]$Serial = "")
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '../../../utility/d4planner/android/controller-bridge')).Path
$apk = Join-Path $project 'app/build/outputs/apk/debug/app-debug.apk'
if (-not (Test-Path $apk)) { throw "Missing APK; run build-android.ps1 first or download artifact to this path." }
if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { throw "adb not found in PATH" }
$argsList = @()
if ($Serial) { $argsList += @('-s', $Serial) }
$argsList += @('install', '-r', $apk)
& adb @argsList
if ($LASTEXITCODE -ne 0) { throw "ADB install failed" }
Write-Host "Open Controller Bridge POC on C, then enable service manually in Accessibility Settings."
