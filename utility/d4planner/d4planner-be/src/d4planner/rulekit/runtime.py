"""Production lifecycle adapter for the BE-owned Rule Kit worker."""

from __future__ import annotations

import os
import copy
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
        self._pending_transition = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "RuleKitRuntimeService":
        values = os.environ if environment is None else environment
        executable = Path(values.get("D4PLANNER_RULEKIT_EXECUTABLE", ""))
        worker = Path(values.get("D4PLANNER_RULEKIT_WORKER", str(Path(__file__).with_name("worker.js"))))
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
        # The installed Python package owns the adapter. Rule Kit owns its
        # private executable bootstrap; no calculation modules are imported here.
        installation = values.get("D4_RULEKIT_INSTALLATION_ROOT")
        rulekit_root = (Path(installation) / "utility" / "d4-rulekit" if installation
                        else Path(__file__).resolve().parents[4] / "d4planner-rulekit")
        if installation and (Path(installation) / "utility/d4planner/d4planner-rulekit").is_dir():
            rulekit_root = Path(installation) / "utility/d4planner/d4planner-rulekit"
        bootstrap = Path(values.get("D4PLANNER_RULEKIT_BOOTSTRAP", str(
            rulekit_root / "application" / "src" / "runtime" / "bootstrap.js")))
        if not bootstrap.is_absolute() or not bootstrap.is_file():
            raise ValueError("Rule Kit bootstrap must be an absolute existing file")
        specification = LaunchSpecification(
            executable=str(executable),
            args=(str(bootstrap), str(worker)),
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
        try:
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
        except BaseException:
            await self.stop()
            raise

    async def snapshot_api(self, method: str, request: dict | None = None, *, on_health=None) -> dict | list:
        """Transport/lifecycle adapter only. Decisions belong to the Node Rule Kit."""
        async with self._management_lock:
            if self._pending_transition is not None:
                pending_method, pending_request, result = self._pending_transition
                if (method, request) != (pending_method, pending_request):
                    raise RuntimeError("snapshot transition pending; retry the same operation before another mutation")
            else:
                if self.client is None:
                    raise RuntimeError("Rule Kit worker is not running")
                result = await self.client.snapshot_call(method, request)
                if not isinstance(result, dict) or not result.get("restartRequired"):
                    if on_health is not None:
                        await on_health(await self.client.snapshot_call("getCapabilities"))
                    return result
                # This is a durable Rule Kit intent, not a successful activation.
                # Retain it across callback/stop/start errors so rollback retry
                # cannot accidentally become a second rollback operation.
                self._pending_transition = (method, copy.deepcopy(request), result)
            try:
                if on_health is not None and self.client is not None:
                    await on_health(await self.client.snapshot_call("getCapabilities"))
                self.client = await self.wrapper.reconfigure()
                active = await self.client.snapshot_call("getActive")
                if (active.get("workerGeneration") != self.wrapper.generation
                    or active.get("restartRequired") is not False
                    or active.get("calculationAvailability") not in {"READY", "UNAVAILABLE"}
                    or (active.get("calculationAvailability") == "READY" and not isinstance(active.get("active"), dict))):
                    raise RuntimeError("snapshot transition worker generation unverified")
                if "selectionRevision" in result:
                    binding = active.get("active")
                    if (active.get("calculationAvailability") != "READY" or not isinstance(binding, dict)
                        or binding.get("entryId") != result.get("entryId")
                        or binding.get("selectionRevision") != result["selectionRevision"]):
                        raise RuntimeError("snapshot transition active binding unverified")
                # Full integrity/compatibility verification remains inside getActive
                # in Rule Kit. BE only checks identity of the acknowledged intent.
                capabilities = await self.client.snapshot_call("getCapabilities")
                if any(capabilities.get(key) != active.get(key) for key in
                       ("active", "workerGeneration", "calculationAvailability", "restartRequired")):
                    raise RuntimeError("snapshot transition health binding inconsistent")
                if on_health is not None:
                    await on_health(capabilities)
                self._pending_transition = None
                return {**result, "afterRestart": active}
            except BaseException:
                # Do not leave a callable old client or advertise success on
                # partial failure. The same operation may explicitly roll forward.
                await self.stop()
                raise

    async def stop(self) -> None:
        self.client = None
        await self.wrapper.stop()

