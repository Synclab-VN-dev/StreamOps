param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [switch]$Runtime,
    [switch]$Launch,
    [ValidateRange(10, 120)][int]$TimeoutSeconds = 45
)
$ErrorActionPreference = 'Stop'
if ($Runtime -and $Launch) { throw "Choose -Runtime or -Launch, not both" }
$file = Get-Item -LiteralPath $ExePath -ErrorAction Stop
if ($file.Length -lt 25000) { throw "EXE too small: $($file.Length) bytes" }

$stream = [System.IO.File]::OpenRead($file.FullName)
try {
    $reader = [System.IO.BinaryReader]::new($stream)
    if ($reader.ReadUInt16() -ne 0x5A4D) { throw "Invalid DOS signature" }
    $stream.Position = 0x3c
    $peOffset = $reader.ReadInt32()
    if ($peOffset -lt 64 -or $peOffset -gt ($file.Length - 6)) { throw "Invalid PE offset" }
    $stream.Position = $peOffset
    $peSignature = $reader.ReadUInt32()
    $machine = $reader.ReadUInt16()
    if ($peSignature -ne 0x00004550 -or $machine -ne 0x8664) {
        throw "Expected Windows x64 PE, got signature=$peSignature machine=$machine"
    }
} finally { $stream.Dispose() }

$hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
Write-Host "[PASS] Portable Windows x64 EXE: $($file.FullName)"
Write-Host "[PASS] SHA256: $hash"

if ($Runtime) {
    # The released EXE executes an in-process native-window self-test and
    # reports actual Tauri window state + cursor mode transitions. This check
    # must FAIL (not silently skip) when GUI creation is unavailable on CI.
    $report = Join-Path ([IO.Path]::GetTempPath()) ("d4-overlay-smoke-{0}.json" -f [Guid]::NewGuid())
    $env:D4_OVERLAY_SMOKE_REPORT = $report
    $proc = $null
    try {
        $proc = Start-Process -FilePath $file.FullName -ArgumentList '--self-test' -PassThru
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            throw "Timed out waiting for native GUI self-test after $TimeoutSeconds seconds"
        }
        if ($proc.ExitCode -ne 0) {
            $details = if (Test-Path $report) { Get-Content $report -Raw } else { "No runtime report" }
            throw "Native GUI smoke failed (exit=$($proc.ExitCode)): $details"
        }
        if (-not (Test-Path $report)) { throw "Missing native GUI smoke report" }
        $result = Get-Content $report -Raw | ConvertFrom-Json
        if ($result.ok -ne $true) { throw "Native smoke did not report PASS: $(Get-Content $report -Raw)" }
        $required = @(
            'always-on-top',
            'frameless',
            'fixed-size',
            'not-fullscreen',
            'global-hotkeys-registered',
            'native-click-through-roundtrip',
            'interactive-recovered'
        )
        foreach ($check in $required) {
            if ($check -notin @($result.checks)) { throw "Missing native smoke check: $check" }
            Write-Host "[PASS] Native GUI: $check"
        }
        $proc.Refresh()
        if (-not $proc.HasExited) { throw "Native GUI process did not exit" }
        Write-Host "[PASS] Native GUI start, state transitions, and exit cleanly"
    }
    finally {
        if ($proc) {
            $proc.Refresh()
            if (-not $proc.HasExited) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $proc.WaitForExit(5000) | Out-Null
            }
        }
        Remove-Item -LiteralPath $report -Force -ErrorAction SilentlyContinue
        Remove-Item Env:D4_OVERLAY_SMOKE_REPORT -ErrorAction SilentlyContinue
    }
}

if ($Launch) {
    # Real-A optional launch test. It does not claim to verify game-focus or
    # physical global key dispatch; those require a human in Diablo IV.
    $proc = Start-Process -FilePath $file.FullName -PassThru
    try {
        Start-Sleep -Seconds 4
        $proc.Refresh()
        if ($proc.HasExited) { throw "Overlay exited early: $($proc.ExitCode)" }
        if ($proc.MainWindowHandle -eq 0) { throw "Overlay has no desktop window" }
        Write-Host "[PASS] GUI process/window alive: PID $($proc.Id)"
        # Request a normal WM_CLOSE before resorting to forceful cleanup.
        $proc.CloseMainWindow() | Out-Null
        if (-not $proc.WaitForExit(5000)) { throw "Overlay failed to close gracefully" }
        Write-Host "[PASS] Overlay closes without a stuck process"
    }
    finally {
        $proc.Refresh()
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    }
}
