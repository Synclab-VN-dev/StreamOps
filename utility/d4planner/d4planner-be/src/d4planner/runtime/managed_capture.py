"""Capture child owned by the foreground Backend, never by Task Scheduler.

Closing the stdin pipe requests graceful shutdown, including on Backend death.
Status is accepted only with this launch's ownership token, never from a stale/foreign runtime.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import uuid4


class ManagedCaptureRuntime:
    def __init__(self, root: Path, on_health, *, spawn=None):
        self.owner_token = uuid4().hex
        self.root = root
        self.on_health = on_health
        self.spawn = spawn or asyncio.create_subprocess_exec
        self.process = None
        self.monitor = None
        self.state = 'STARTING'
        self.detail = 'Starting capture runtime'
        self._last_health = None
        self.on_status = None

    async def start(self):
        if self.process is not None:
            return
        environment = dict(os.environ)
        for name in ('D4PLANNER_BOOTSTRAP_FILE', 'D4PLANNER_RUNTIME_FACTORY'):
            environment.pop(name, None)
        try:
            self.process = await self.spawn(
                sys.executable, '-m', 'd4planner.daemon', '--managed-by-hud',
                '--owner-token', self.owner_token, '--block', '--controller-profile', 'xbox16', '--home', str(self.root),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, env=environment,
                **({'creationflags': 0x08000000} if os.name == 'nt' else {}),
            )
        except OSError as error:
            self.state, self.detail = 'BLOCKED', f'Capture process could not start: {type(error).__name__}'
            if self.on_status:
                await self.on_status(self.state, self.detail)
            await self.on_health('ERROR')
            return
        self.monitor = asyncio.create_task(self._monitor(), name='managed-capture-health')

    async def _refresh(self):
        if self.process.returncode is not None:
            self.state = 'BLOCKED'
            self.detail = ('Another capture runtime owns this data folder' if self.process.returncode == 5
                           else f'Capture process exited ({self.process.returncode})')
        try:
            payload = json.loads((self.root / 'state/runtime.json').read_text(encoding='utf-8'))
            if payload.get('extras', {}).get('runtime', {}).get('ownerToken') == self.owner_token:
                self.state = payload['state'] if self.process.returncode is None else 'BLOCKED'
                self.detail = payload.get('lastError') or payload.get('detail') or self.detail
        except (OSError, ValueError, KeyError, TypeError):
            pass
        # A running hook is not proof of an identified character/equipment snapshot.
        health = 'DEGRADED' if self.state in {'STARTING', 'BOOTSTRAPPING', 'NVDA_READY',
            'TOLK_READY', 'GAME_STARTING', 'GAME_ATTACHED', 'CAPTURE_READY',
            'WAITING_FOR_GAME', 'RUNNING', 'DEGRADED'} else 'ERROR'
        observed = (health, self.state, self.detail)
        if self._last_health != observed:
            self._last_health = observed
            if self.on_status:
                await self.on_status(self.state, self.detail)
            await self.on_health(health)

    async def _monitor(self):
        try:
            while True:
                await self._refresh()
                await asyncio.sleep(.25)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.state, self.detail = 'BLOCKED', f'Capture status failed: {type(error).__name__}'
            if self.on_status:
                await self.on_status(self.state, self.detail)
            await self.on_health('ERROR')

    async def stop(self):
        if self.monitor:
            self.monitor.cancel()
            try:
                await self.monitor
            except asyncio.CancelledError:
                pass
            self.monitor = None
        child, self.process = self.process, None
        if child is not None and child.returncode is None:
            if child.stdin:
                child.stdin.close()
            try:
                await asyncio.wait_for(child.wait(), 20)
            except asyncio.TimeoutError:
                # This handle came from our spawn; never stop by a discovered PID.
                child.terminate()
                await child.wait()
        self.state = 'STOPPED'
