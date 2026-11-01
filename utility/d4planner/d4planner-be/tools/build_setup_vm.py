#!/usr/bin/env python3
"""Build a committed D4Planner checkout on a Windows SSH builder; retrieve artifacts.

Requires an already-running, provisioned Windows VM. Does not start a VM, install
system tools, alter SSH configuration, publish a Release, or use the VM's checkout.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[4]
GUEST = Path(__file__).with_name('build_setup_vm.ps1')
SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=3']


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def call(args, **kwargs):
    return subprocess.run(args, check=True, timeout=120, **kwargs)


class WindowsSSH:
    def __init__(self, host):
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host):
            raise ValueError('Use an SSH alias (configure HostName/Port/User in ~/.ssh/config)')
        self.host = host

    def powershell(self, code, *, timeout=120, stdout=subprocess.PIPE):
        encoded = base64.b64encode(code.encode('utf-16-le')).decode('ascii')
        return subprocess.run(['ssh', *SSH_OPTIONS, self.host, 'powershell.exe',
            '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-EncodedCommand', encoded], timeout=timeout, stdout=stdout,
            stderr=subprocess.STDOUT, text=True, check=False)

    def upload(self, local, remote):
        call(['scp', *SSH_OPTIONS, str(local), f'{self.host}:{remote}'])

    def download(self, remote, local):
        call(['scp', *SSH_OPTIONS, f'{self.host}:{remote}', str(local)])


def source_snapshot(repo, ref, archive):
    """A shallow Git checkout preserves the exact commit; no untracked files/secrets."""
    head = call(['git', '-C', str(repo), 'rev-parse', '--verify', '--end-of-options', f'{ref}^{{commit}}'],
                capture_output=True, text=True).stdout.strip()
    if not re.fullmatch('[0-9a-f]{40}', head):
        raise ValueError('Expected a SHA-1 Git commit')
    with tempfile.TemporaryDirectory(prefix='d4planner-source-') as temp:
        checkout = Path(temp) / 'source'
        call(['git', 'init', '--quiet', str(checkout)], capture_output=True)
        call(['git', '-C', str(checkout), 'config', 'core.autocrlf', 'false'])
        call(['git', '-C', str(checkout), 'config', 'core.fileMode', 'false'])
        call(['git', '-C', str(checkout), '-c', 'protocol.file.allow=always',
              'fetch', '--quiet', '--depth=1', str(repo.resolve()), head], capture_output=True)
        call(['git', '-C', str(checkout), '-c', 'core.hooksPath=/dev/null',
              'checkout', '--quiet', '--detach', head], capture_output=True)
        plan = json.loads((checkout / 'utility/d4planner/d4planner-be/release1/package-plan.json').read_text())
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(checkout.rglob('*')):
                if path.is_symlink():
                    raise ValueError(f'Source symlink requires explicit Windows handling: {path.relative_to(checkout)}')
                # Git requires even empty refs/ directories for a detached clone.
                if path.is_file() or path.is_dir():
                    bundle.write(path, path.relative_to(checkout).as_posix())
    return head, plan['version']


def verify_download(output, result, head, version):
    expected = {f'D4Planner-Setup-{version}.exe', 'release-metadata.json', 'SHA256SUMS', 'UAT.md'}
    if result.get('sourceHead') != head or result.get('version') != version:
        raise ValueError('VM result source/version mismatch')
    if result.get('exitCode') != 0 or set(result.get('files', {})) != expected:
        raise ValueError('VM build failed or returned an unexpected artifact set')
    for name, sha in result['files'].items():
        if digest(output / name) != sha:
            raise ValueError(f'Download checksum mismatch: {name}')
    meta = json.loads((output / 'release-metadata.json').read_text(encoding='utf-8-sig'))
    name = f'D4Planner-Setup-{version}.exe'
    if (meta.get('sourceHead') != head or meta.get('version') != version or
            meta.get('artifact') != name or meta.get('sha256') != digest(output / name) or
            meta.get('bytes') != (output / name).stat().st_size or
            meta.get('snapshotIncluded') is not False or
            meta.get('artifactClass') != 'D4PLANNER_APPLICATION_NO_SNAPSHOT' or
            meta.get('runtimeHealth') != 'PASS'):
        raise ValueError('Downloaded package metadata mismatch')
    if (output / 'SHA256SUMS').read_text(encoding='utf-8-sig') != f"{meta['sha256']}  {name}\n":
        raise ValueError('Downloaded SHA256SUMS mismatch')


def cancel_owned(ssh, remote):
    # PID reuse must not let a disconnected/expired run kill another process.
    return ssh.powershell(fr"""
$ErrorActionPreference='Stop'
$root={ps_quote(remote)}
$owner=Get-Content -LiteralPath ($root+'/owner.json') -Raw | ConvertFrom-Json
$p=Get-Process -Id $owner.pid -ErrorAction SilentlyContinue
if ($p -and $p.StartTime.ToUniversalTime().Ticks.ToString() -eq $owner.started) {{
  $cmd=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$owner.pid)).CommandLine
  if ($cmd -notlike ('*'+$root.Replace('/','\')+'*') -and $cmd -notlike ('*'+$root+'*')) {{
    # EncodedCommand hides the path; the random run root and exact start time
    # still bind this owner record to the process that wrote it.
    if ($cmd -notmatch 'EncodedCommand') {{ throw 'Owner command mismatch' }}
  }}
  & taskkill.exe /PID $owner.pid /T /F
  exit $LASTEXITCODE
}}
if (-not (Test-Path -LiteralPath ($root+'/result.json'))) {{ throw 'Cannot confirm owned child-process cleanup' }}
""", timeout=30)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm', required=True, help='SSH alias for the Windows builder')
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--ref', default='HEAD', help='Committed source only; working-tree edits are excluded')
    parser.add_argument('--version', help='Defaults to package-plan.json at --ref')
    parser.add_argument('--output', type=Path, required=True, help='New local directory; never overwritten')
    parser.add_argument('--python', default='python', help='Python 3.12.10 executable inside the VM')
    parser.add_argument('--timeout', type=int, default=3600, help='Build deadline in seconds')
    parser.add_argument('--check', action='store_true', help='Check VM/toolchain only, without building')
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    ssh = WindowsSSH(args.vm)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    run_id = uuid.uuid4().hex
    remote = None
    running = False
    try:
        init = ssh.powershell(fr"""
$ErrorActionPreference='Stop'
$p=Join-Path $env:TEMP 'd4planner-build-{run_id}'
New-Item -ItemType Directory -Path $p | Out-Null
$p.Replace('\','/')
""")
        (output / 'connection.log').write_text(init.stdout)
        if init.returncode:
            raise RuntimeError('SSH/bootstrap failed; see connection.log (VM must already have SSH configured)')
        remote = init.stdout.strip()
        if not re.fullmatch(r'[A-Za-z]:/[^\r\n]*d4planner-build-' + run_id, remote):
            raise RuntimeError('Unexpected VM work directory')
        (output / 'run.json').write_text(json.dumps({'vm': args.vm, 'remote': remote, 'runId': run_id}, indent=2))
        ssh.upload(GUEST, remote + '/build_setup_vm.ps1')
        invoke = f"& {ps_quote(remote + '/build_setup_vm.ps1')} -Root {ps_quote(remote)} -Python {ps_quote(args.python)}"
        check = ssh.powershell(invoke + ' -CheckOnly; exit $LASTEXITCODE')
        (output / 'preflight.log').write_text(check.stdout)
        if check.returncode:
            raise RuntimeError('Windows toolchain preflight failed; see preflight.log')
        if args.check:
            print(f'VM preflight PASS: {output / "preflight.log"}')
            return 0
        with tempfile.TemporaryDirectory(prefix='d4planner-transfer-') as temp:
            archive = Path(temp) / 'source.zip'
            head, plan_version = source_snapshot(args.repo, args.ref, archive)
            version = args.version or plan_version
            if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version) or version != plan_version:
                raise ValueError('Version must match package-plan.json at the chosen commit')
            sha = digest(archive)
            ssh.upload(archive, remote + '/source.zip')
        print(f'Building {head} / {version} on {args.vm}; log: {output / "transport.log"}', flush=True)
        running = True
        with (output / 'transport.log').open('w') as log:
            completed = ssh.powershell(invoke + f' -SourceHead {head} -Version {version} -SourceSha256 {sha}; exit $LASTEXITCODE',
                                      timeout=args.timeout, stdout=log)
        if completed.returncode == 255:
            raise RuntimeError('SSH connection lost during build')
        running = False
        # Fetch diagnostics even when compilation/tests fail. Never recursively
        # copy the build tree, runtime inputs, credentials or private VM data.
        for name in ('result.json', 'build.log'):
            ssh.download(remote + '/' + name, output / name)
        result = json.loads((output / 'result.json').read_text(encoding='utf-8-sig'))
        if completed.returncode or result.get('exitCode') != 0:
            raise RuntimeError(f'VM build failed (SSH exit {completed.returncode}); see result.json and build.log')
        expected = {f'D4Planner-Setup-{version}.exe', 'release-metadata.json', 'SHA256SUMS', 'UAT.md'}
        if set(result.get('files', {})) != expected:
            raise ValueError('Unexpected VM artifact filenames')
        staging = output / 'download'
        staging.mkdir()
        for name in sorted(expected):
            ssh.download(remote + '/out/build/verified-artifact/' + name, staging / name)
        verify_download(staging, result, head, version)
        for name in sorted(expected):
            (staging / name).replace(output / name)
        staging.rmdir()
        print(f'PASS: {output / f"D4Planner-Setup-{version}.exe"}')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        if running and remote:
            try:
                cancelled = cancel_owned(ssh, remote)
                (output / 'cancel.log').write_text(cancelled.stdout)
                if cancelled.returncode:
                    print(f'Owned-process cleanup needs attention: {remote}', file=sys.stderr)
            except Exception as cleanup_error:
                print(f'Cannot confirm VM cleanup: {cleanup_error}; run directory {remote}', file=sys.stderr)
        (output / 'failure.txt').write_text(str(error) + '\n')
        print(f'FAILED: {error}. Evidence: {output}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
