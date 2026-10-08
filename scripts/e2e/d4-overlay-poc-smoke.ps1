param(
    [Parameter(Mandatory=$true)][string]$ExePath,
    [switch]$Launch
)
$ErrorActionPreference='Stop'
$file=Get-Item -LiteralPath $ExePath -ErrorAction Stop
if ($file.Length -lt 25000) { throw "EXE too small: $($file.Length) bytes" }
$stream=[System.IO.File]::OpenRead($file.FullName)
try {
    $reader=[System.IO.BinaryReader]::new($stream)
    if ($reader.ReadUInt16() -ne 0x5A4D) { throw 'Invalid DOS signature' }
    $stream.Position=0x3c
    $peOffset=$reader.ReadInt32()
    if ($peOffset -lt 64 -or $peOffset -gt ($file.Length - 6)) { throw 'Invalid PE offset' }
    $stream.Position=$peOffset
    $peSignature=$reader.ReadUInt32()
    $machine=$reader.ReadUInt16()
    if ($peSignature -ne 0x00004550 -or $machine -ne 0x8664) {
        throw "Expected Windows x64 PE, got machine=$machine"
    }
} finally { $stream.Dispose() }
$hash=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
Write-Host "[PASS] Portable Windows x64 EXE: $($file.FullName)"
Write-Host "[PASS] SHA256 $hash"

if ($Launch) {
    # Only in a logged-in interactive desktop (not a headless CI runner).
    $proc=Start-Process -FilePath $file.FullName -PassThru
    try {
        Start-Sleep -Seconds 4
        $proc.Refresh()
        if ($proc.HasExited) { throw "Early exit: $($proc.ExitCode)" }
        Write-Host "[PASS] GUI process alive: PID $($proc.Id)"
    } finally {
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue }
    }
}
