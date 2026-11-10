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
import time
from datetime import datetime
from uuid import uuid4
from .store import atomic_write_json
from .model import RuntimeState


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
        self._operation = asyncio.Lock()
        self._payload = {}
        self.preferences = root / 'state/capture-preferences.json'
        self.manual_pause = False
        self.preference_error = False
        try:
            preference = json.loads(self.preferences.read_text(encoding='utf-8'))
            if set(preference) != {'manualPause'} or type(preference['manualPause']) is not bool:
                raise ValueError('Invalid capture preference')
            self.manual_pause = preference['manualPause']
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            self.preference_error = True

    async def command(self, operation):
        if operation not in {'start', 'stop', 'restart'}:
            raise ValueError('UNSUPPORTED_METHOD')
        async with self._operation:
            # Persist operator intent before a lifecycle change. A write failure must
            # not claim that a manual pause will survive Backend restart.
            atomic_write_json(self.preferences, {'manualPause': operation == 'stop'})
            self.manual_pause = operation == 'stop'
            self.preference_error = False
            try:
                if operation in {'stop', 'restart'}:
                    await self._stop()
                if operation != 'stop':
                    await self._start()
            except (OSError, asyncio.TimeoutError):
                self.state, self.detail = 'BLOCKED', 'Owned capture cleanup failed; retry or collect logs'
                await self._notify()
                raise
            await self._notify()
            return self.status()

    def status(self):
        live = self.process is not None and self.process.returncode is None
        payload = self._payload if live else {}
        dependencies = {}
        for name in ('nvda', 'game'):
            process = payload.get(name)
            if isinstance(process, dict) and type(process.get('pid')) is int:
                dependencies[name] = f"Observed PID {process['pid']}"
        tolk = payload.get('tolk')
        if isinstance(tolk, dict):
            dependencies['tolk'] = 'READY' if str(tolk.get('reader') or '').lower() == 'nvda' and tolk.get('speech') and not tolk.get('error') else 'NOT READY'
        marker = payload.get('extras', {}).get('inputMarker', {})
        if not isinstance(marker, dict):
            marker = {}
        receipt_state = 'UNAVAILABLE'
        nvda = payload.get('nvda')
        if isinstance(nvda, dict):
            try:
                from .storage import canonical
                receipt = json.loads((self.root / 'private/nvda-capture-consumer.json').read_text(encoding='utf-8'))
                matched = (receipt.get('pid') == nvda.get('pid')
                    and canonical(receipt['dataRoot']) == canonical(self.root)
                    and datetime.fromisoformat(nvda['started_at']).timestamp() <= float(receipt['writtenAtUnix']) <= time.time() + 1)
                receipt_state = 'VALIDATED' if matched else 'MISMATCH'
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                pass
        count = payload.get('extras', {}).get('speechEventCount')
        return {'speechEvents': count if type(count) is int and count >= 0 else None,
                'dataRootReceipt': receipt_state, 'state': self.state, 'detail': self.detail,
                'pid': self.process.pid if live else None, 'manualPause': self.manual_pause,
                'mode': 'BLOCK · Silent', 'controllerProfile': 'xbox16',
                'lastEventAt': payload.get('lastEventAt'),
                'inputObserved': bool(marker.get('lastInputAt')), 'dependencies': dependencies,
                'observedAt': payload.get('updatedAt')}


    async def start(self):
        async with self._operation:
            await self._start()

    async def _start(self):
        if self.preference_error or self.manual_pause:
            self.state = 'BLOCKED' if self.preference_error else 'STOPPED'
            self.detail = 'Capture preference unreadable; use Start Capture to resume' if self.preference_error else 'Manually paused'
            await self._notify()
            return
        if self.process is not None:
            if self.process.returncode is None:
                return
            await self._stop()
        self.owner_token = uuid4().hex
        self._payload = {}
        self.state, self.detail = 'STARTING', 'Starting capture runtime'
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
        self._payload = {}
        try:
            payload = json.loads((self.root / 'state/runtime.json').read_text(encoding='utf-8'))
            if (self.process.returncode is None and payload.get('supervisorPid') == self.process.pid
                    and payload.get('extras', {}).get('runtime', {}).get('ownerToken') == self.owner_token):
                self.state = RuntimeState(payload['state']).value
                detail = payload.get('lastError') or payload.get('detail')
                if isinstance(detail, str):
                    self.detail = detail
                self._payload = payload
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        await self._notify()

    async def _notify(self):
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
        async with self._operation:
            await self._stop()

    async def _stop(self):
        if self.monitor:
            self.monitor.cancel()
            try:
                await self.monitor
            except asyncio.CancelledError:
                pass
            self.monitor = None
        child = self.process
        if child is not None and child.returncode is None:
            if child.stdin:
                child.stdin.close()
            try:
                await asyncio.wait_for(child.wait(), 20)
            except asyncio.TimeoutError:
                # This handle came from our spawn; never stop by a discovered PID.
                child.terminate()
                await asyncio.wait_for(child.wait(), 5)
        self.process = None
        self.state = 'STOPPED'
        self.detail = 'Manually paused' if self.manual_pause else 'Capture stopped'
        self._payload = {}
