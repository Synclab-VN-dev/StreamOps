"""Foreground Backend entrypoint owned by the native D4Planner shell.

This is deliberately not the standalone capture daemon.  It owns no Scheduled
Task and never detaches.  The parent supplies a private bootstrap descriptor by
environment, receives lifecycle events on stdout, and owns stdin; EOF is parent
death and therefore stops the child.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
import signal
import sys
from typing import Any, Protocol


PROTOCOL = "d4planner-managed/v1"
CONTRACT = "d4planner-r1-contract/1.0.0-candidate.5"
BOOTSTRAP_ENV = "D4PLANNER_BOOTSTRAP_FILE"
RUNTIME_FACTORY_ENV = "D4PLANNER_RUNTIME_FACTORY"


class BootstrapError(ValueError):
    pass


class ManagedRuntime(Protocol):
    async def start(self) -> dict[str, Any]: ...
    async def stop(self) -> None: ...
    async def handle_control(self, command: dict[str, Any]) -> dict[str, Any] | None: ...


class BaseRuntime:
    """S2-only runtime used before a higher stack layer registers services."""

    def __init__(self, bootstrap: dict[str, Any]):
        self.bootstrap = bootstrap

    async def start(self) -> dict[str, Any]:
        target_folder = Path(self.bootstrap["targetFolder"])
        return {
            "wsEndpoint": self.bootstrap["wsEndpoint"],
            "health": {
                "durableState": "READY",
                "targetRepository": "READY",
                "targetJsonCount": sum(
                    1 for entry in target_folder.iterdir()
                    if entry.is_file() and entry.suffix.lower() == ".json"
                ),
                "services": "BASE_RUNTIME",
                "wsTransport": "PENDING_S5", "ruleKitWorker": "PENDING_S3",
            },
        }

    async def stop(self) -> None:
        return None

    async def handle_control(self, command: dict[str, Any]) -> dict[str, Any] | None:
        del command
        return None


def create_runtime(bootstrap: dict[str, Any]) -> ManagedRuntime:
    factory_name = os.environ.get(RUNTIME_FACTORY_ENV)
    if not factory_name:
        return BaseRuntime(bootstrap)
    module_name, separator, attribute = factory_name.partition(":")
    if not separator or not module_name or not attribute:
        raise BootstrapError("runtime factory must use module:attribute syntax")
    try:
        factory = getattr(importlib.import_module(module_name), attribute)
        runtime = factory(bootstrap)
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        raise BootstrapError(f"runtime factory unavailable: {type(exc).__name__}") from exc
    if any(not callable(getattr(runtime, method, None)) for method in ("start", "stop", "handle_control")):
        raise BootstrapError("runtime factory returned an invalid service lifecycle")
    return runtime


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise BootstrapError(f"{field} must be a non-empty string")
    return value


def load_bootstrap(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BootstrapError("bootstrap descriptor is missing")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise BootstrapError("bootstrap descriptor must be owner-only")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapError("bootstrap descriptor is unreadable or invalid JSON") from exc
    if not isinstance(data, dict):
        raise BootstrapError("bootstrap descriptor must be an object")
    required = {
        "protocol", "contractVersion", "ownerInstanceId", "childInstanceId",
        "generation", "dataDir", "targetFolder", "wsEndpoint", "credential",
    }
    if set(data) != required:
        raise BootstrapError("bootstrap descriptor fields do not match the managed contract")
    if data["protocol"] != PROTOCOL or data["contractVersion"] != CONTRACT:
        raise BootstrapError("bootstrap protocol or contract version mismatch")
    for field in ("ownerInstanceId", "childInstanceId", "credential"):
        _string(data[field], field)
    if not isinstance(data["generation"], int) or data["generation"] < 1:
        raise BootstrapError("generation must be a positive integer")
    endpoint = data["wsEndpoint"]
    if not isinstance(endpoint, dict) or set(endpoint) != {"host", "port"}:
        raise BootstrapError("wsEndpoint must contain only host and port")
    if endpoint["host"] not in {"127.0.0.1", "::1"}:
        raise BootstrapError("wsEndpoint must be loopback")
    if not isinstance(endpoint["port"], int) or not 0 <= endpoint["port"] <= 65535:
        raise BootstrapError("wsEndpoint port is invalid")
    if len(data["credential"]) < 32:
        raise BootstrapError("credential is too short")
    return data


def _emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, separators=(",", ":")), flush=True)


async def _run_managed(bootstrap: dict[str, Any], runtime: ManagedRuntime) -> int:
    data_dir = Path(_string(bootstrap["dataDir"], "dataDir")).resolve()
    target_folder = Path(_string(bootstrap["targetFolder"], "targetFolder")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    target_folder.mkdir(parents=True, exist_ok=True)

    stopping = False
    exit_reason = "PARENT_EOF"

    def stop_requested(_signum: int, _frame: object) -> None:
        nonlocal stopping, exit_reason
        stopping = True
        exit_reason = "SIGNAL"

    signal.signal(signal.SIGTERM, stop_requested)
    signal.signal(signal.SIGINT, stop_requested)

    try:
        readiness = await runtime.start()
    except Exception as exc:
        await runtime.stop()
        _emit({"event": "STARTUP_FAILED", "code": type(exc).__name__})
        return 70
    endpoint = readiness.get("wsEndpoint")
    health = readiness.get("health")
    if not isinstance(endpoint, dict) or not isinstance(health, dict):
        await runtime.stop()
        _emit({"event": "STARTUP_FAILED", "code": "INVALID_SERVICE_READINESS"})
        return 70
    _emit({
        "event": "READY",
        "protocol": PROTOCOL,
        "contractVersion": CONTRACT,
        "ownerInstanceId": bootstrap["ownerInstanceId"],
        "childInstanceId": bootstrap["childInstanceId"],
        "generation": bootstrap["generation"],
        "pid": os.getpid(),
        "wsEndpoint": endpoint,
        "health": health,
    })

    while not stopping:
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":  # inherited pipe closed: parent died/exited
            break
        try:
            command = json.loads(line)
        except json.JSONDecodeError:
            _emit({"event": "ERROR", "code": "INVALID_CONTROL_MESSAGE"})
            continue
        if (
            isinstance(command, dict)
            and command.get("type") == "shutdown"
            and command.get("ownerInstanceId") == bootstrap["ownerInstanceId"]
            and command.get("childInstanceId") == bootstrap["childInstanceId"]
            and command.get("generation") == bootstrap["generation"]
        ):
            exit_reason = "OWNER_STOP"
            break
        if (
            isinstance(command, dict)
            and command.get("ownerInstanceId") == bootstrap["ownerInstanceId"]
            and command.get("childInstanceId") == bootstrap["childInstanceId"]
            and command.get("generation") == bootstrap["generation"]
        ):
            response = await runtime.handle_control(command)
            if response is not None:
                _emit({"event": "CONTROL_RESULT", **response})
                continue
        _emit({"event": "ERROR", "code": "OWNERSHIP_MISMATCH"})

    try:
        await runtime.stop()
    except Exception as exc:
        _emit({"event": "ERROR", "code": "SERVICE_STOP_FAILED", "detail": type(exc).__name__})
        return 71
    _emit({
        "event": "EXIT",
        "ownerInstanceId": bootstrap["ownerInstanceId"],
        "childInstanceId": bootstrap["childInstanceId"],
        "generation": bootstrap["generation"],
        "reason": exit_reason,
    })
    return 0


def run_managed(bootstrap: dict[str, Any]) -> int:
    return asyncio.run(_run_managed(bootstrap, create_runtime(bootstrap)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="d4planner-managed-backend")
    parser.parse_args(argv)
    descriptor = os.environ.get(BOOTSTRAP_ENV)
    if not descriptor:
        print("managed bootstrap environment is missing", file=sys.stderr)
        return 64
    try:
        bootstrap = load_bootstrap(Path(descriptor))
        return run_managed(bootstrap)
    except BootstrapError as exc:
        print(f"managed bootstrap rejected: {exc}", file=sys.stderr)
        return 65


if __name__ == "__main__":
    raise SystemExit(main())
