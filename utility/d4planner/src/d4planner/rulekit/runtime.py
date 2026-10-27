"""Production lifecycle adapter for the BE-owned Rule Kit worker."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .client import RuleKitClient
import asyncio
from .process import LaunchSpecification, RuleKitProcessWrapper


PRODUCTION_ENVIRONMENT = (
    "D4_RULEKIT_DATA_ROOT",
    "D4_RULEKIT_INSTALLATION_ROOT",
    "D4_RULEKIT_PROFILE_JSON",
    "D4_RULEKIT_SNAPSHOT_ROOT",
    "D4_RULEKIT_CHROMIUM_EXECUTABLE",
    "D4_RULEKIT_MAX_CONTEXTS",
    "D4_RULEKIT_BROWSER_MAX_QUEUE",
    "D4_RULEKIT_MAX_SESSIONS",
    "D4_RULEKIT_SESSION_TTL_MS",
    "D4_RULEKIT_OPERATION_TIMEOUT_MS",
    "D4_RULEKIT_CLEANUP_TIMEOUT_MS",
)


class RuleKitRuntimeService:
    """Own one long-lived production worker for the Backend lifetime."""

    def __init__(self, wrapper: RuleKitProcessWrapper):
        self.wrapper = wrapper
        self.client: RuleKitClient | None = None
        self._management_lock = asyncio.Lock()

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "RuleKitRuntimeService":
        values = os.environ if environment is None else environment
        executable = Path(values.get("D4PLANNER_RULEKIT_EXECUTABLE", ""))
        worker = Path(values.get("D4PLANNER_RULEKIT_WORKER", ""))
        working_directory = Path(values.get("D4PLANNER_RULEKIT_WORKING_DIR", ""))
        for path, label in (
            (executable, "Rule Kit executable"),
            (worker, "Rule Kit worker"),
        ):
            if not path.is_absolute() or not path.is_file():
                raise ValueError(f"{label} must be an absolute existing file")
        if not working_directory.is_absolute() or not working_directory.is_dir():
            raise ValueError("Rule Kit working directory must be an absolute existing directory")
        forwarded = {
            name: values[name] for name in PRODUCTION_ENVIRONMENT if values.get(name)
        }
        required = {"D4_RULEKIT_PROFILE_JSON", "D4_RULEKIT_SNAPSHOT_ROOT"}
        managed = forwarded.get("D4_RULEKIT_DATA_ROOT")
        if managed and (not Path(managed).is_absolute() or not Path(forwarded.get("D4_RULEKIT_INSTALLATION_ROOT", "")).is_absolute()):
            raise ValueError("Rule Kit data and installation roots must be absolute")
        if not managed and not required.issubset(forwarded):
            raise ValueError("production Rule Kit profile and snapshot root are required")
        specification = LaunchSpecification(
            executable=str(executable),
            args=(str(worker),),
            working_directory=working_directory,
            environment_allow_list=forwarded,
            readiness_timeout=15,
            graceful_stop_timeout=8,
            kill_timeout=3,
            operation_timeout=15,
            max_pending=32,
            max_restarts=2,
        )
        return cls(RuleKitProcessWrapper(specification))

    async def start(self) -> dict:
        self.client = await self.wrapper.start()
        providers = await self.client.list_providers()
        health = await self.wrapper.inspect_health()
        if not health["ready"] or not providers:
            await self.stop()
            raise RuntimeError("production Rule Kit has no ready provider")
        result = {**health, "providers": providers}
        if self.wrapper.specification.environment_allow_list.get("D4_RULEKIT_DATA_ROOT"):
            result["snapshotCapabilities"] = await self.client.snapshot_call("getCapabilities")
            result["calculationAvailability"] = result["snapshotCapabilities"]["calculationAvailability"]
            result["calculationReason"] = result["snapshotCapabilities"]["reason"]
        else:
            result["calculationAvailability"] = "READY"
        return result

    async def snapshot_api(self, method: str, request: dict | None = None) -> dict | list:
        """Transport/lifecycle adapter only. Decisions belong to the Node Rule Kit."""
        async with self._management_lock:
            if self.client is None:
                raise RuntimeError("Rule Kit worker is not running")
            result = await self.client.snapshot_call(method, request)
            if isinstance(result, dict) and result.get("restartRequired"):
                self.client = await self.wrapper.reconfigure()
                # A fresh client invalidates all old session refs. The Rule Kit
                # persisted the selection and owns its validation at startup.
                active = await self.client.snapshot_call("getActive")
                return {**result, "afterRestart": active}
            return result

    async def stop(self) -> None:
        await self.wrapper.stop()
        self.client = None

