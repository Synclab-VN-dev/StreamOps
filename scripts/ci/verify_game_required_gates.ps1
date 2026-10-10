# E2E-01: a PR cannot report a green "windows" job while game gates silently skip.
# A repository admin must also require the "windows" check in the Master Ruleset.
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$gameScope = $env:GAME_SCOPE
$eventName = $env:CI_EVENT_NAME
if ($eventName -eq 'pull_request') {
    if ([string]::IsNullOrWhiteSpace($env:CI_BASE_SHA) -or
        [string]::IsNullOrWhiteSpace($env:CI_HEAD_SHA)) {
        throw "E2E-01: missing PR base/head SHA; cannot audit change detection"
    }
    $changed = @(git diff --name-only "$($env:CI_BASE_SHA)...$($env:CI_HEAD_SHA)")
    if ($LASTEXITCODE -ne 0) { throw "E2E-01: git diff failed" }
    $mustRun = @($changed | Where-Object {
        $_ -like 'streamops/*' -or
        $_ -like 'scripts/e2e/issue85*' -or
        $_ -like 'scripts/devices/a-windows/issue85*' -or
        $_ -like 'scripts/ci/*game*' -or
        $_ -eq 'pyproject.toml' -or
        $_ -eq '.github/workflows/tests.yml'
    }).Count -gt 0
    Write-Host "E2E-01 changed files: $($changed -join ', ')"
} elseif ($eventName -eq 'push') {
    $mustRun = $true
} else {
    throw "E2E-01: unsupported event '$eventName'"
}

if ($mustRun -and $gameScope -ne 'true') {
    throw "E2E-01: GameService changed but scope detector disabled all gates"
}
if (!$mustRun -and $gameScope -ne 'false' -and $gameScope -ne 'true') {
    throw "E2E-01: invalid/missing scope output '$gameScope'"
}

if ($gameScope -eq 'true') {
    $gates = [ordered]@{
        G1 = $env:GAME_G1
        G2 = $env:GAME_G2
        G3 = $env:GAME_G3
        G4 = $env:GAME_G4
        G5 = $env:GAME_G5
        G6 = $env:GAME_G6
        Wheel = $env:GAME_WHEEL
        RaceThreeRuns = $env:GAME_RACE
        FullRegression = $env:GAME_REGRESSION
    }
    $failures = @()
    foreach ($entry in $gates.GetEnumerator()) {
        Write-Host "E2E-01 $($entry.Key): $($entry.Value)"
        if ($entry.Value -ne 'success') {
            $failures += "$($entry.Key)=$($entry.Value)"
        }
    }
    if ($failures.Count -gt 0) {
        throw "E2E-01: game gates not all successful: $($failures -join ', ')"
    }
    Write-Host "E2E-01 PASS: all G1-G6 + installed wheel + race + regression required"
} else {
    Write-Host "E2E-01 PASS: no game-relevant files changed; game gate skip permitted"
}
