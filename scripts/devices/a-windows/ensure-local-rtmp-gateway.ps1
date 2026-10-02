param(
    [string]$Version = "1.21.1",
    [string]$LanIp = "192.168.1.8"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$ToolRoot = Join-Path $RepoRoot ".streamops\tools\mediamtx"
$RuntimeRoot = Join-Path $RepoRoot ".streamops\node\mediamtx"
$ExePath = Join-Path $ToolRoot "mediamtx.exe"
$ConfigPath = Join-Path $RuntimeRoot "mediamtx.yml"
$PidPath = Join-Path $RuntimeRoot "mediamtx.pid"
$StdoutPath = Join-Path $RuntimeRoot "mediamtx.stdout.log"
$StderrPath = Join-Path $RuntimeRoot "mediamtx.stderr.log"

New-Item -ItemType Directory -Force -Path $ToolRoot | Out-Null
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

function Test-TcpPort {
    param([int]$Port)
    try {
        return (Test-NetConnection -ComputerName "127.0.0.1" -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded
    } catch {
        return $false
    }
}

function Ensure-FirewallRule {
    param(
        [string]$Name,
        [ValidateSet("TCP", "UDP")]
        [string]$Protocol,
        [int]$Port
    )

    $existing = Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        return
    }

    try {
        New-NetFirewallRule `
            -DisplayName $Name `
            -Direction Inbound `
            -Action Allow `
            -Profile Private `
            -Protocol $Protocol `
            -LocalPort $Port `
            -RemoteAddress LocalSubnet | Out-Null
    } catch {
        Write-Warning "Could not create firewall rule '$Name'. Run this script from an elevated PowerShell if LAN clients cannot connect."
    }
}

if (-not (Test-Path $ExePath)) {
    $zipName = "mediamtx_v${Version}_windows_amd64.zip"
    $downloadUrl = "https://github.com/bluenviron/mediamtx/releases/download/v$Version/$zipName"
    $zipPath = Join-Path $env:TEMP $zipName
    $extractRoot = Join-Path $env:TEMP ("streamops-mediamtx-" + [guid]::NewGuid().ToString("N"))

    Write-Host "Downloading MediaMTX v$Version..."
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath

    try {
        Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force
        $downloadedExe = Get-ChildItem -Path $extractRoot -Filter "mediamtx.exe" -Recurse | Select-Object -First 1
        if ($null -eq $downloadedExe) {
            throw "mediamtx.exe was not found in the downloaded archive."
        }
        Copy-Item -Path $downloadedExe.FullName -Destination $ExePath -Force
    } finally {
        Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item -Path $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$config = @"
logLevel: info
logDestinations: [stdout]

api: false
metrics: false
pprof: false
playback: false

rtsp: false

rtmp: true
rtmpEncryption: "no"
rtmpAddress: :1935

hls: true
hlsAddress: :8888
hlsAllowOrigins: ["*"]

webrtc: true
webrtcAddress: :8889
webrtcAllowOrigins: ["*"]
webrtcLocalUDPAddress: :8189
webrtcAdditionalHosts: [$LanIp]

srt: false
moq: false

paths:
  all_others:
"@

[IO.File]::WriteAllText($ConfigPath, $config, [Text.UTF8Encoding]::new($false))

Ensure-FirewallRule -Name "StreamOps MediaMTX RTMP" -Protocol TCP -Port 1935
Ensure-FirewallRule -Name "StreamOps MediaMTX HLS" -Protocol TCP -Port 8888
Ensure-FirewallRule -Name "StreamOps MediaMTX WebRTC HTTP" -Protocol TCP -Port 8889
Ensure-FirewallRule -Name "StreamOps MediaMTX WebRTC ICE" -Protocol UDP -Port 8189

$running = $null
if (Test-Path $PidPath) {
    $savedPid = Get-Content $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($savedPid -match "^\d+$") {
        $running = Get-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue
    }
}

if ($null -eq $running) {
    if (Test-TcpPort 1935) {
        throw "TCP port 1935 is already in use by another process. Refusing to start a second RTMP gateway."
    }

    $process = Start-Process `
        -FilePath $ExePath `
        -ArgumentList @($ConfigPath) `
        -WorkingDirectory $RuntimeRoot `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath `
        -WindowStyle Hidden `
        -PassThru

    Set-Content -Path $PidPath -Value $process.Id -Encoding ASCII

    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        if ((Test-TcpPort 1935) -and (Test-TcpPort 8888) -and (Test-TcpPort 8889)) {
            $running = $process
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if ($null -eq $running) {
        throw "MediaMTX did not open RTMP/HLS/WebRTC ports within 15 seconds. See $StderrPath"
    }
}

Write-Host ""
Write-Host "Local RTMP gateway READY"
Write-Host "PID:              $($running.Id)"
Write-Host "OBS publish base: rtmp://127.0.0.1:1935/live"
Write-Host "LAN RTMP base:    rtmp://$LanIp:1935/live"
Write-Host "LAN HLS viewer:   http://$LanIp:8888/live/<stream-key>"
Write-Host "LAN WebRTC:       http://$LanIp:8889/live/<stream-key>"
Write-Host ""
Write-Host "The stream key is intentionally not stored or printed by this script."
