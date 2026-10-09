$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '../../../utility/d4planner/android/controller-bridge')).Path
if (-not (Get-Command gradle -ErrorAction SilentlyContinue)) {
    throw "Gradle not installed. Install Gradle 8.9 and Android SDK 35, or download the APK from PR Actions artifacts."
}
& gradle -p $project :app:testDebugUnitTest :app:assembleDebug --no-daemon
if ($LASTEXITCODE -ne 0) { throw "Gradle Android POC build/tests failed" }
Write-Host ("Debug APK: " + (Join-Path $project 'app/build/outputs/apk/debug/app-debug.apk'))
