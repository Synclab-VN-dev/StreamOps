"""Lifecycle of an enrolled, dedicated local Windows builder; never a shared VM."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import time

STATE = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'streamops/d4planner-builder'


class ManagedBuilder:
    def __init__(self, alias, config=None):
        self.path = Path(config) if config else STATE/'config.json'
        self.config = None
        self.lock = None
        self.started = False
        self.process = None
        if self.path.exists():
            candidate = json.loads(self.path.read_text())
            if candidate.get('alias') == alias:
                if candidate.get('schemaVersion') != 1 or candidate.get('dedicatedBuilder') is not True:
                    raise ValueError('Refusing to manage a VM not enrolled as a dedicated builder')
                self.config = candidate
        if config and not self.config:
            raise ValueError('VM configuration does not match the SSH alias')

    @property
    def ssh_config(self):
        return self.config.get('sshConfig') if self.config else None

    def acquire(self):
        if not self.config:
            return
        import fcntl
        self.lock = (self.path.parent/'build.lock').open('a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close(); self.lock = None
            raise RuntimeError('This dedicated VM already has an active build')

    def ensure_running(self, ssh):
        ready = ssh.powershell('Write-Output D4_BUILDER_READY', timeout=25)
        if ready.returncode == 0 and 'D4_BUILDER_READY' in ready.stdout:
            return
        if not self.config:
            raise RuntimeError('SSH unavailable and no dedicated local VM configuration found')
        # QEMU owns an exclusive disk lock; a failed start cannot attach an active disk.
        command = self.config['startCommand']
        if not isinstance(command, list) or not command:
            raise ValueError('Expected an argv list for VM startup')
        print('Starting dedicated Windows builder...', flush=True)
        with (self.path.parent/'startup.log').open('a') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.process = process
        self.started = True
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('VM startup exited; see startup.log')
            time.sleep(3)
            ready = ssh.powershell('Write-Output D4_BUILDER_READY', timeout=25)
            if ready.returncode == 0 and 'D4_BUILDER_READY' in ready.stdout:
                return
        raise RuntimeError('VM did not become SSH-ready within 240 seconds')

    def close(self, ssh, *, leave_running=False):
        try:
            if self.started and not leave_running and (self.process is None or self.process.poll() is None):
                # Never shut down an external/already-running VM.
                outcome = ssh.powershell('shutdown.exe /s /t 5; exit $LASTEXITCODE', timeout=25)
                if outcome.returncode:
                    raise RuntimeError('Could not request shutdown of the VM started by this run')
                if self.process is not None:
                    self.process.wait(timeout=60)
        finally:
            if self.lock:
                self.lock.close(); self.lock = None
