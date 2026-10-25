"""Template-method lifecycle wrapper for the BE-owned Node Rule Kit worker."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .client import RuleKitClient
from .protocol import PROTOCOL_VERSION, ProtocolError, validate_ready


class ProcessState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    STOPPING = "STOPPING"
    EXITED = "EXITED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class LaunchSpecification:
    executable: str
    args: tuple[str, ...]
    working_directory: Path
    environment_allow_list: dict[str, str] = field(default_factory=dict)
    readiness_timeout: float = 10.0
    graceful_stop_timeout: float = 5.0
    kill_timeout: float = 2.0
    operation_timeout: float = 5.0
    max_pending: int = 32
    max_restarts: int = 2

    def __post_init__(self) -> None:
        if not self.executable or not self.working_directory.is_dir():
            raise ValueError("valid executable and working_directory are required")
        numeric = (
            self.readiness_timeout,
            self.graceful_stop_timeout,
            self.kill_timeout,
            self.operation_timeout,
        )
        if any(value <= 0 for value in numeric) or self.max_pending <= 0 or self.max_restarts < 0:
            raise ValueError("timeouts/capacity must be positive and restart budget non-negative")


@dataclass
class SpawnedProcess:
    process: asyncio.subprocess.Process
    child_instance_id: str
    generation: int

    @property
    def pid(self) -> int:
        return self.process.pid


class ProcessDriver(Protocol):
    async def spawn(self, specification: LaunchSpecification, *, instance_id: str, generation: int) -> SpawnedProcess: ...
    async def request_graceful_stop(self, child: SpawnedProcess, client: RuleKitClient | None) -> None: ...
    async def terminate_owned_child(self, child: SpawnedProcess) -> None: ...


class AsyncioProcessDriver:
    """OS mechanics only; never searches for or kills a process by name."""

    async def spawn(
        self, specification: LaunchSpecification, *, instance_id: str, generation: int
    ) -> SpawnedProcess:
        inherited_names = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC")
        environment = {name: os.environ[name] for name in inherited_names if name in os.environ}
        environment.update(specification.environment_allow_list)
        environment.update(
            {
                "D4_RULEKIT_WORKER_INSTANCE_ID": instance_id,
                "D4_RULEKIT_WORKER_GENERATION": str(generation),
            }
        )
        process = await asyncio.create_subprocess_exec(
            specification.executable,
            *specification.args,
            cwd=specification.working_directory,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=(0x00000200 if os.name == "nt" else 0),  # CREATE_NEW_PROCESS_GROUP
        )
        return SpawnedProcess(process, instance_id, generation)

    async def request_graceful_stop(self, child: SpawnedProcess, client: RuleKitClient | None) -> None:
        if client is not None:
            await client.shutdown_worker()

    async def terminate_owned_child(self, child: SpawnedProcess) -> None:
        if child.process.returncode is not None:
            return
        if os.name == "nt":
            child.process.terminate()
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGTERM)


class RuleKitProcessWrapper:
    def __init__(self, specification: LaunchSpecification, driver: ProcessDriver | None = None) -> None:
        self.specification = specification
        self.driver = driver or AsyncioProcessDriver()
        self.owner_instance_id = str(uuid.uuid4())
        self.worker_instance_id: str | None = None
        self.generation = 0
        self.state = ProcessState.STOPPED
        self.client: RuleKitClient | None = None
        self._child: SpawnedProcess | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._exit_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._restart_count = 0
        self.last_exit: dict | None = None

    async def start(self) -> RuleKitClient:
        async with self._lifecycle_lock:
            if self.state == ProcessState.READY and self.client is not None:
                return self.client
            if self.state in {ProcessState.STARTING, ProcessState.STOPPING}:
                raise RuntimeError(f"worker lifecycle is busy: {self.state}")
            return await self._start_locked()

    async def _start_locked(self) -> RuleKitClient:
        self.state = ProcessState.STARTING
        self.generation += 1
        instance_id = str(uuid.uuid4())
        self.worker_instance_id = instance_id
        child: SpawnedProcess | None = None
        try:
            child = await self.driver.spawn(
                self.specification, instance_id=instance_id, generation=self.generation
            )
            self._child = child
            assert child.process.stdout is not None and child.process.stdin is not None
            line = await asyncio.wait_for(
                child.process.stdout.readline(), self.specification.readiness_timeout
            )
            if not line:
                raise ProtocolError("worker exited before READY")
            try:
                ready = json.loads(line)
            except json.JSONDecodeError:
                raise ProtocolError("worker READY is not JSON") from None
            validate_ready(ready, instance_id=instance_id, generation=self.generation)
            self.client = RuleKitClient(
                reader=child.process.stdout,
                writer=child.process.stdin,
                worker_instance_id=instance_id,
                worker_generation=self.generation,
                operation_timeout=self.specification.operation_timeout,
                max_pending=self.specification.max_pending,
            )
            self.state = ProcessState.READY
            self._exit_task = asyncio.create_task(self._watch_exit(child))
            if child.process.stderr is not None:
                self._stderr_task = asyncio.create_task(self._drain_stderr(child.process.stderr))
            return self.client
        except Exception:
            self.state = ProcessState.FAILED
            if child is not None:
                await self._bounded_terminate(child)
            self._child = None
            self.client = None
            raise

    async def stop(self, reason: str = "OWNER_EXIT") -> None:
        del reason
        async with self._lifecycle_lock:
            if self.state in {ProcessState.STOPPED, ProcessState.EXITED}:
                return
            self.state = ProcessState.STOPPING
            child, client = self._child, self.client
            if child is None:
                self.state = ProcessState.STOPPED
                return
            try:
                await self.driver.request_graceful_stop(child, client)
                await asyncio.wait_for(
                    child.process.wait(), self.specification.graceful_stop_timeout
                )
            except (TimeoutError, BrokenPipeError, ConnectionError):
                await self._bounded_terminate(child)
            finally:
                if client is not None:
                    await client.close()
                await self._cancel_background_tasks()
                self._child = None
                self.client = None
                self.state = ProcessState.STOPPED

    async def restart(self) -> RuleKitClient:
        if self._restart_count >= self.specification.max_restarts:
            raise RuntimeError("Rule Kit restart budget exhausted")
        self._restart_count += 1
        await self.stop("RESTART")
        return await self.start()

    async def inspect_health(self) -> dict:
        child = self._child
        return {
            "ready": self.state == ProcessState.READY
            and child is not None
            and child.process.returncode is None,
            "protocolVersion": PROTOCOL_VERSION,
            "workerInstanceId": self.worker_instance_id,
            "workerGeneration": self.generation,
            "reason": self.state.value,
        }

    async def _watch_exit(self, child: SpawnedProcess) -> None:
        return_code = await child.process.wait()
        self.last_exit = {
            "pid": child.pid,
            "workerInstanceId": child.child_instance_id,
            "generation": child.generation,
            "exitCode": return_code,
        }
        if self._child is child and self.state not in {ProcessState.STOPPING, ProcessState.STOPPED}:
            self.state = ProcessState.FAILED
            if self.client is not None:
                await self.client.close()
            self.client = None

    async def _bounded_terminate(self, child: SpawnedProcess) -> None:
        await self.driver.terminate_owned_child(child)
        try:
            await asyncio.wait_for(child.process.wait(), self.specification.kill_timeout)
        except TimeoutError:
            if child.process.returncode is None:
                child.process.kill()
                await child.process.wait()

    async def _cancel_background_tasks(self) -> None:
        current = asyncio.current_task()
        tasks = [task for task in (self._exit_task, self._stderr_task) if task and task is not current]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._exit_task = None
        self._stderr_task = None

    @staticmethod
    async def _drain_stderr(reader: asyncio.StreamReader) -> None:
        # Logs are intentionally discarded here: production integration supplies
        # a sanitized logger, never forwards private worker stderr over IPC.
        while await reader.readline():
            pass
