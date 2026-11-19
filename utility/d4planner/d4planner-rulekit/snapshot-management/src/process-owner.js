'use strict';
const path = require('node:path');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const {SnapshotError} = require('./trust');
const run = promisify(execFile);

// Windows signal 0 requires rights unrelated to read-only process identity.
// Query creation time instead; no signal is sent to another process.
async function windowsIdentity(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) throw new SnapshotError('SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN');
  // Ordinary startup must not require WMI or PowerShell module discovery.
  // Retain a read-only CIM fallback for processes whose StartTime is protected.
  // CIM stores microseconds: normalize native ticks to preserve existing leases.
  const script = `$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $PSModuleAutoLoadingPreference='None';
try {$p=[System.Diagnostics.Process]::GetProcessById(${pid})} catch [System.ArgumentException] {'null'; exit 0}
try {
  try {$created=$p.StartTime.ToUniversalTime()} catch {
    Import-Module "$PSHOME/Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1" -ErrorAction Stop;
    Import-Module "$PSHOME/Modules/CimCmdlets/CimCmdlets.psd1" -ErrorAction Stop;
    $cim=CimCmdlets\\Get-CimInstance Win32_Process -Filter 'ProcessId=${pid}';
    if($null -eq $cim){'null'; exit 0}; $created=$cim.CreationDate.ToUniversalTime()
  }
  $created=$created.AddTicks(-($created.Ticks % 10));
  '{"pid":${pid},"startedAt":"'+$created.ToString('o')+'"}'
} finally {$p.Dispose()}`;
  try {
    const {stdout} = await run(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32/WindowsPowerShell/v1.0/powershell.exe'),
      ['-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',Buffer.from(script,'utf16le').toString('base64')],
      {windowsHide:true,timeout:4000,maxBuffer:8192});
    const value=JSON.parse(stdout.replace(/^\uFEFF/,'').trim());
    if(value===null)return null;
    if(value.pid!==pid || typeof value.startedAt!=='string' || !Number.isFinite(Date.parse(value.startedAt)))throw new SyntaxError();
    return {startedAt:value.startedAt};
  } catch(error) {
    const reason=error.code==='ERR_CHILD_PROCESS_STDIO_MAXBUFFER'?'OUTPUT_LIMIT':
      error.killed||error.code==='ETIMEDOUT'?'TIMEOUT':error instanceof SyntaxError?'INVALID_RESPONSE':'QUERY_FAILED';
    throw new SnapshotError('SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN',`SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN:${reason}`);
  }
}
function classifyWindowsOwner(record, lastWriteMs, current) {
  if(current===null)return 'DEAD';
  if(record.processIdentity!==undefined){
    if(typeof record.processIdentity?.startedAt!=='string' || !Number.isFinite(Date.parse(record.processIdentity.startedAt)))throw new SnapshotError('SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN');
    if(record.processIdentity.startedAt===current.startedAt)return 'LIVE';
    if(Date.parse(current.startedAt)>Date.parse(record.processIdentity.startedAt))return 'REUSED';
    throw new SnapshotError('SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN');
  }
  // Legacy leases lack creation identity. Only retire if Windows proves the
  // process was created AFTER the lease was written (1s filesystem tolerance).
  // Equal/older/unknown times stay fail-closed; PID existence alone is insufficient.
  return Number.isFinite(lastWriteMs) && Date.parse(current.startedAt)>lastWriteMs+1000?'REUSED':'LIVE';
}
async function currentIdentity(){
  if(process.platform!=='win32')return undefined;
  const identity=await windowsIdentity(process.pid);
  if(!identity)throw new SnapshotError('SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN');
  return identity;
}
async function ownerState(record, lastWriteMs){
  if(process.platform==='win32')return classifyWindowsOwner(record,lastWriteMs,await windowsIdentity(record.pid));
  try {process.kill(record.pid,0);return 'LIVE';}
  catch(error){if(error.code==='ESRCH')return 'DEAD';throw new SnapshotError('SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN');}
}
module.exports={currentIdentity,ownerState,classifyWindowsOwner,windowsIdentity};
