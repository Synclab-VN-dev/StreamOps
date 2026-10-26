"""Production lifecycle adapter for the BE-owned Rule Kit worker."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .client import RuleKitClient
from .process import LaunchSpecification, RuleKitProcessWrapper


PRODUCTION_ENVIRONMENT = (
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
        if not required.issubset(forwarded):
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
        return {**health, "providers": providers}

    async def stop(self) -> None:
        await self.wrapper.stop()
        self.client = None

