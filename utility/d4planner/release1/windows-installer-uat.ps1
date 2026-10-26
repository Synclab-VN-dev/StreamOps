[CmdletBinding()]
param(
  [string]$Sandbox = 'C:\Users\huy\StreamOps-UAT\PR150-Installer',
  [string]$EvidenceName = 'evidence',
  [switch]$RegisterAndRun,
  [switch]$Run
)
$ErrorActionPreference = 'Stop'
$taskName = 'StreamOps-PR150-Installer-Native'
if ($RegisterAndRun) {
  if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Test task already exists; refusing overwrite' }
  if (Get-NetTCPConnection -State Listen -LocalPort 38150 -ErrorAction SilentlyContinue) { throw 'Approved port is occupied' }
  $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Sandbox "{1}" -EvidenceName "{2}" -Run' -f $PSCommandPath,$Sandbox,$EvidenceName)
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings | Out-Null
  Start-ScheduledTask -TaskName $taskName
  Write-Output "Started approved isolated task $taskName"
  exit 0
}
if (-not $Run) { throw 'Select RegisterAndRun or Run' }
$evidence = Join-Path $Sandbox $EvidenceName
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
Start-Transcript -Path (Join-Path $evidence 'execution.log') -Force | Out-Null
try {
  if ((Get-Process -Id $PID).SessionId -eq 0) { throw 'Interactive desktop session required' }
  if (Get-NetTCPConnection -State Listen -LocalPort 38150 -ErrorAction SilentlyContinue) { throw 'Approved port is occupied' }
  $protectedBefore = @(Get-Process -Name 'Diablo IV','steam','obs64','nvda' -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,SessionId)
  $protectedBefore | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $evidence 'protected-before.json') -Encoding UTF8
  $python = Join-Path $Sandbox 'harness\python\python.exe'
  $driver = Join-Path $Sandbox 'artifacts\windows_setup_e2e.py'
  $package = Join-Path $Sandbox 'artifacts\D4Planner-1.0.1.zip'
  $packageHash = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
  & $python $driver --sandbox (Join-Path $Sandbox ($EvidenceName + '-run')) --setup-old (Join-Path $Sandbox 'artifacts\D4Planner-Setup-1.0.0.exe') --setup-new (Join-Path $Sandbox 'artifacts\D4Planner-Setup-1.0.1.exe') --package-new $package --package-sha $packageHash --output (Join-Path $evidence 'acceptance.json') 2>&1 | Tee-Object -FilePath (Join-Path $evidence 'driver.log')
  $code = $LASTEXITCODE
  $protectedAfter = @(Get-Process -Name 'Diablo IV','steam','obs64','nvda' -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,SessionId)
  $protectedAfter | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $evidence 'protected-after.json') -Encoding UTF8
  if (Compare-Object ($protectedBefore.Id | Sort-Object) ($protectedAfter.Id | Sort-Object)) { throw 'Protected process PIDs changed; inspect evidence' }
  exit $code
} finally { Stop-Transcript | Out-Null }
