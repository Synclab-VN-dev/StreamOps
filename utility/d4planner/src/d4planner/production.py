"""Concrete Release 1 Backend composition root."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from .character.repository import (
    EquipmentRepositoryIncompatible, EquipmentRepositoryReadError,
    EquipmentRepositoryTransient, EquipmentRepositoryUnavailable,
    ReadOnlyEquipmentRepository,
)
from .release1.assessment import EquipmentAssessmentService, EquipmentSnapshot
from .release1.capture_adapter import EquipmentCaptureAdapter, RepositoryEquipmentCaptureAdapter
from .release1.persistence import AssessmentBinding, DurableHudStore
from .release1.service import EquipmentAssessmentCoordinator
from .release1.target_repository import (
    ActivatedTarget, TargetChanged, TargetError, TargetRepository, TargetValidator,
)
from .rulekit import RuleKitRuntimeService
from .transport import (
    D4PlannerWebSocketServer, HudHub, TargetActivationError, WebSocketServerConfig,
)


CONTRACT_REVISION = "d4planner-r1-contract/1.0.0-candidate.5"
ORIGIN = "tauri://localhost"
TAURI_BROWSER_ORIGINS = ("http://tauri.localhost", "https://tauri.localhost")


class RepositoryEquipmentEventSource:
    """Bounded DB polling for a producer that exposes no notification contract.

    Only this Backend adapter polls. The FE remains WebSocket push-only.
    """

    def __init__(
        self, runtime: "ProductionBackendRuntime", repository: ReadOnlyEquipmentRepository,
        *, character_id: str, character_display_name: str, interval_seconds: float = 0.1,
        maximum_backoff_seconds: float = 2.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("Equipment repository interval must be positive")
        self.runtime = runtime
        self.repository = repository
        self.adapter = RepositoryEquipmentCaptureAdapter(repository)
        self.character_id = character_id
        self.character_display_name = character_display_name
        self.interval_seconds = interval_seconds
        self.maximum_backoff_seconds = max(interval_seconds, maximum_backoff_seconds)
        self._last_revision = 0
        self._task: asyncio.Task[None] | None = None
        self.health_status = "STARTING"
        self.last_error: str | None = None
        self.poll_count = 0
        self.last_poll_duration_ns = 0
        self.maximum_poll_duration_ns = 0
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Equipment repository source already started")
        self._stopping = False
        try:
            await self._consume_latest()
        except EquipmentRepositoryTransient as error:
            await self._set_health("DEGRADED", str(error))
        self._task = asyncio.create_task(self._run(), name="equipment-repository-source")

    async def stop(self) -> None:
        self._stopping = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.health_status = "STOPPED"

    async def _consume_latest(self) -> bool:
        started = perf_counter_ns()
        try:
            projection = await asyncio.to_thread(self.repository.projection_snapshot)
        finally:
            self.last_poll_duration_ns = perf_counter_ns() - started
            self.maximum_poll_duration_ns = max(
                self.maximum_poll_duration_ns, self.last_poll_duration_ns,
            )
            self.poll_count += 1
        cursor = projection.revision
        if cursor is None or cursor[0] <= self._last_revision:
            await self._set_health("HEALTHY", None)
            return False
        revision = cursor[0]
        current = await asyncio.to_thread(
            self.adapter.snapshot,
            character_id=self.character_id,
            character_display_name=self.character_display_name,
            current_revision=revision,
            projection=projection,
        )
        await self.runtime.ingest_snapshot(current)
        self._last_revision = revision
        await self._set_health("HEALTHY", None)
        return True

    async def _set_health(self, status: str, error: str | None) -> None:
        if self.health_status == status and self.last_error == error:
            return
        previous = self.health_status
        self.health_status, self.last_error = status, error
        if previous != "STARTING" or status != "HEALTHY":
            await self.runtime.capture_health_changed(status)

    async def _run(self) -> None:
        delay = self.interval_seconds
        while True:
            await asyncio.sleep(delay)
            try:
                await self._consume_latest()
                delay = self.interval_seconds
            except asyncio.CancelledError:
                raise
            except EquipmentRepositoryTransient as error:
                await self._set_health("DEGRADED", str(error))
                delay = min(self.maximum_backoff_seconds, max(delay * 2, self.interval_seconds))
            except (EquipmentRepositoryUnavailable, EquipmentRepositoryIncompatible) as error:
                await self._set_health("ERROR", str(error))
                delay = self.maximum_backoff_seconds
            except (EquipmentRepositoryReadError, ValueError, TypeError) as error:
                await self._set_health("ERROR", f"CAPTURE_PRODUCT_FAILURE:{type(error).__name__}")
                delay = self.maximum_backoff_seconds
            except Exception as error:  # background tasks must fail visibly, never silently
                await self._set_health("ERROR", f"CAPTURE_UNEXPECTED_FAILURE:{type(error).__name__}")
                delay = self.maximum_backoff_seconds


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _policy_version(target: ActivatedTarget) -> str:
    policy = target.document["assessmentPolicy"]
    return policy["version"] + "+" + policy["weightProfile"]["profileId"]


def _binding(runtime_instance_id: str, current: EquipmentSnapshot, target: ActivatedTarget) -> AssessmentBinding:
    return AssessmentBinding(
        runtime_instance_id, current.character_id, current.current_revision,
        target.target_id, target.content_sha256, target.selection_revision,
        _policy_version(target),
    )


def _unbound_hud(
    revision: int, runtime_instance_id: str, generation: int,
    *, target: ActivatedTarget | None = None, current: EquipmentSnapshot | None = None,
    rulekit_state: str = "READY", produced_at: str | None = None,
) -> dict[str, Any]:
    if target and current:
        state = "BOUND"
    elif target:
        state = "TARGET_ONLY"
    elif current:
        state = "CHARACTER_ONLY"
    else:
        state = "STARTUP"
    policy = target.document["assessmentPolicy"] if target else None
    criteria = policy["criteria"] if policy else []
    weights = policy["weightProfile"] if policy else None
    total_weight = sum(
        weights["coreWeight"] if criterion["core"] else weights["nonCoreWeight"]
        for criterion in criteria
    ) if weights else 0
    target_context = None if target is None else {
        "targetId": target.target_id, "displayName": target.display_name,
        "buildDisplayName": target.display_name, "contentSha256": target.content_sha256,
        "selectionRevision": target.selection_revision, "policyVersion": _policy_version(target),
    }
    character_context = None if current is None else {
        "characterId": current.character_id, "displayName": current.character_display_name,
        "currentRevision": current.current_revision,
    }
    return {
        "schemaVersion": "d4planner-hud/v1", "hudRevision": revision,
        "producedAt": produced_at or _now(),
        "backend": {"runtimeInstanceId": runtime_instance_id, "generation": generation},
        "context": {
            "state": state, "character": character_context, "target": target_context,
            "binding": None, "selectionError": None,
        },
        "health": {
            "capture": current.capture_health if current else "UNKNOWN",
            "scoreFreshness": "NO_DATA", "ruleKit": rulekit_state,
        },
        "score": {
            "status": "NO_DATA", "value": None, "passedWeight": 0, "evaluableWeight": 0,
            "evaluationCounts": {
                "evaluatedCriteria": 0, "totalCriteria": len(criteria),
                "evaluatedWeight": 0, "totalWeight": total_weight,
            },
            "failIssueCount": 0, "warnCount": 0, "itemsPassing": 0,
            "itemsTargeted": len({criterion["slotId"] for criterion in criteria}),
        },
        "equipment": [], "recommendation": None,
        "provenance": {
            "producer": "D4PLANNER_BE", "assessmentVersion": CONTRACT_REVISION,
            "captureRevision": current.current_revision if current else None,
            "lastObservedAt": current.captured_at if current else None,
        },
    }


class ProductionDomain:
    def __init__(self, runtime: "ProductionBackendRuntime"):
        self.runtime = runtime

    async def list_targets(self) -> dict[str, Any]:
        listing = self.runtime.targets.list()
        return {
            "listRevision": listing.revision,
            "targets": [{
                "targetId": entry.target_id, "displayName": entry.display_name,
                "contentSha256": entry.content_sha256, "byteLength": entry.byte_length,
                "validation": entry.validation, "errorCodes": list(entry.error_codes),
            } for entry in listing.entries],
        }

    async def activate_target(
        self, target_id: str, expected_sha256: str, expected_list_revision: int,
    ) -> dict[str, Any]:
        try:
            target, hud = await self.runtime.activate_target(
                target_id, expected_sha256, expected_list_revision,
            )
        except TargetChanged as exc:
            raise TargetActivationError("TARGET_CHANGED", str(exc), retryable=True) from None
        except TargetError as exc:
            raise TargetActivationError(exc.code, str(exc)) from None
        return {
            "status": "ACTIVATED", "targetId": target.target_id,
            "contentSha256": target.content_sha256,
            "selectionRevision": target.selection_revision,
            "hudRevision": hud["hudRevision"], "hud": hud,
        }


def _resolve_repository_root(configured: str | None, module_file: Path = Path(__file__)) -> Path:
    if configured is not None:
        root = Path(configured).resolve()
        if not Path(configured).is_absolute() or not root.is_dir():
            raise ValueError("configured contract repository root is invalid")
        return root
    required = (
        Path("utility/d4planner/contracts/release1/v1/schemas/target.schema.json"),
        Path("utility/d4-rulekit/providers/maxroll/d4-build-v1.schema.json"),
    )
    for root in (module_file.resolve().parents[3], module_file.resolve().parents[4]):
        if all((root / relative).is_file() for relative in required):
            return root
    raise ValueError("packaged contract repository root cannot be discovered")


class RuntimeHudStore(DurableHudStore):
    """Decorate transport/runtime metadata before the durable commit boundary.

    Equipment scoring remains owned by S4. This adapter only attaches the
    Rule Kit-owned health result and the enclosing Backend generation.
    """
    def __init__(self, path, *, runtime_health, backend_generation):
        self.runtime_health = runtime_health
        self.backend_generation = backend_generation
        super().__init__(path)

    def _factory(self, factory):
        def build(revision):
            payload = factory(revision)
            payload["health"]["ruleKit"] = self.runtime_health()
            payload["backend"]["generation"] = self.backend_generation()
            return payload
        return build

    def commit_if_current(self, binding, payload_factory, committed_at):
        return super().commit_if_current(binding, self._factory(payload_factory), committed_at)

    def commit_context(self, payload_factory, committed_at):
        return super().commit_context(self._factory(payload_factory), committed_at)


class ProductionBackendRuntime:
    """Own dependencies in start order and close them in reverse order."""

    def __init__(self, bootstrap: dict[str, Any], *, rulekit: RuleKitRuntimeService | None = None):
        self.bootstrap = bootstrap
        self.runtime_instance_id = str(bootstrap["childInstanceId"])
        self.generation = int(bootstrap["generation"])
        self.data_dir = Path(bootstrap["dataDir"]).resolve()
        self.target_folder = Path(bootstrap["targetFolder"]).resolve()
        configured_root = os.environ.get("D4PLANNER_REPOSITORY_ROOT")
        repository_root = _resolve_repository_root(configured_root)
        self.rulekit = rulekit
        self.targets = TargetRepository(
            self.target_folder, self.data_dir / "selected-target.json",
            TargetValidator.from_contract_tree(repository_root),
        )
        self.rulekit_state = "UNAVAILABLE"
        self.rulekit_diagnostics = {"calculationAvailability": "UNAVAILABLE", "reason": "STARTING"}
        self.store = RuntimeHudStore(self.data_dir / "hud.sqlite3",
            runtime_health=lambda: self.rulekit_state, backend_generation=lambda: self.generation)
        self.capture = EquipmentCaptureAdapter()
        self.scorer = EquipmentAssessmentService()
        self.coordinator = EquipmentAssessmentCoordinator(self.scorer, self.store, lambda _: None)
        self.current: EquipmentSnapshot | None = None
        self.hub: HudHub | None = None
        self.server: D4PlannerWebSocketServer | None = None
        self.capture_source: RepositoryEquipmentEventSource | None = None
        self._ingest_lock = asyncio.Lock()
        trace = os.environ.get("D4PLANNER_LATENCY_TRACE")
        self.latency_trace = Path(trace) if trace else None
        if self.latency_trace is not None and not self.latency_trace.is_absolute():
            raise ValueError("latency trace path must be absolute")

    async def start(self) -> dict[str, Any]:
        if self.rulekit is None:
            environment = dict(os.environ)
            environment.setdefault("D4_RULEKIT_DATA_ROOT", str(self.data_dir / "rulekit"))
            environment.setdefault("D4_RULEKIT_INSTALLATION_ROOT", str(_resolve_repository_root()))
            self.rulekit = RuleKitRuntimeService.from_environment(environment)
        rulekit_health = await self.rulekit.start()
        availability = rulekit_health.get("calculationAvailability", "READY")
        self.rulekit_state = "READY" if availability == "READY" else "UNAVAILABLE"
        self.rulekit_diagnostics = rulekit_health.get("snapshotCapabilities", {"calculationAvailability": availability})
        try:
            target = self.targets.get_active()
            initial = self.store.commit_context(
                lambda revision: _unbound_hud(
                    revision, self.runtime_instance_id, self.generation,
                    target=target, rulekit_state=self.rulekit_state,
                ), _now(),
            )
            self.hub = HudHub(initial, backend_generation=self.generation)
            self.store.mark_published(initial["hudRevision"])
            domain = ProductionDomain(self)
            endpoint = self.bootstrap["wsEndpoint"]
            self.server = D4PlannerWebSocketServer(
                WebSocketServerConfig(
                    credential=self.bootstrap["credential"],
                    runtime_instance_id=self.runtime_instance_id,
                    backend_generation=self.generation, origin=ORIGIN,
                    browser_origins=TAURI_BROWSER_ORIGINS,
                    host=endpoint["host"], port=endpoint["port"],
                ), domain, self.hub,
            )
            await self.server.start()
            evidence_path = os.environ.get("D4PLANNER_EQUIPMENT_EVIDENCE_FILE")
            capture_state = "READY"
            if evidence_path:
                path = Path(evidence_path)
                if not path.is_absolute() or not path.is_file() or path.is_symlink():
                    raise ValueError("configured Equipment evidence file is invalid")
                try:
                    evidence = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("configured Equipment evidence is unreadable") from exc
                await self.ingest(evidence)
                capture_state = "RECORDED_EVIDENCE_APPLIED"
            repository_path = os.environ.get("D4PLANNER_EQUIPMENT_REPOSITORY_DB")
            if repository_path:
                path = Path(repository_path)
                character_id = os.environ.get("D4PLANNER_CHARACTER_ID", "")
                character_name = os.environ.get("D4PLANNER_CHARACTER_DISPLAY_NAME", "")
                if (not path.is_absolute() or not path.is_file() or path.is_symlink()
                        or not character_id or not character_name):
                    raise ValueError("configured Equipment repository source is invalid")
                self.capture_source = RepositoryEquipmentEventSource(
                    self, ReadOnlyEquipmentRepository(path), character_id=character_id,
                    character_display_name=character_name,
                )
                await self.capture_source.start()
                capture_state = "REPOSITORY_" + self.capture_source.health_status
            return {
                "wsEndpoint": {"host": endpoint["host"], "port": self.server.port},
                "health": {
                    "durableState": "READY", "targetRepository": "READY",
                    "targetJsonCount": len(self.targets.list().entries),
                    "wsTransport": "READY", "ruleKitWorker": self.rulekit_state,
                    "ruleKitProcess": "READY",
                    "ruleKitGeneration": rulekit_health["workerGeneration"],
                    "equipmentCapture": capture_state,
                },
            }
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self.capture_source is not None:
            await self.capture_source.stop()
            self.capture_source = None
        if self.server is not None:
            await self.server.close()
            self.server = None
        if self.rulekit is not None:
            await self.rulekit.stop()

    async def _publish_committed(self, hud: dict[str, Any]) -> tuple[int, str]:
        if self.hub is None:
            raise RuntimeError("HUD hub is not started")
        publish_started_at = _now()
        await self.hub.publish_after_commit(hud)
        self.store.mark_published(hud["hudRevision"])
        return perf_counter_ns(), publish_started_at

    async def _forward_rulekit_health(self, result: dict[str, Any]) -> None:
        """Normalize Rule Kit's answer; no registry/profile policy in the BE."""
        state = "READY" if result.get("calculationAvailability") == "READY" else "UNAVAILABLE"
        self.rulekit_diagnostics = result
        async with self._ingest_lock:
            if state == self.rulekit_state:
                return
            self.rulekit_state = state
            latest = self.store.latest_authoritative()
            if latest is None:
                return
            def build(revision):
                payload = json.loads(json.dumps(latest))
                payload["hudRevision"] = revision
                payload["producedAt"] = _now()
                return payload
            hud = self.store.commit_context(build, _now())
            await self._publish_committed(hud)

    async def snapshot_management(self, method: str, request: dict | None = None):
        if self.rulekit is None:
            raise RuntimeError("Rule Kit service is not started")
        return await self.rulekit.snapshot_api(method, request, on_health=self._forward_rulekit_health)

    async def capture_health_changed(self, status: str) -> None:
        """Publish watcher degradation/recovery without relabelling stale score CURRENT."""
        capture = "HEALTHY" if status == "HEALTHY" else ("STALE" if status == "DEGRADED" else "ERROR")
        async with self._ingest_lock:
            latest = self.store.latest_authoritative()
            if latest is None or (
                latest["health"]["capture"] == capture
                and (status == "HEALTHY" or latest["health"]["scoreFreshness"] == "STALE")
            ):
                return
            def build(revision: int) -> dict[str, Any]:
                payload = json.loads(json.dumps(latest))
                payload["hudRevision"] = revision
                payload["producedAt"] = _now()
                payload["health"]["capture"] = capture
                payload["health"]["scoreFreshness"] = (
                    "STALE" if status != "HEALTHY" else
                    ("NO_DATA" if payload["score"]["status"] == "NO_DATA" else "CURRENT")
                )
                return payload
            hud = self.store.commit_context(build, _now())
            await self._publish_committed(hud)

    def _record_latency(
        self, hud: dict[str, Any], timing: dict[str, int],
        published_ns: int, publish_started_at: str,
    ) -> None:
        if self.latency_trace is None:
            return
        capture_ns = timing["captureReceivedNs"]
        record = {
            "schemaVersion": "d4planner-stage-latency/v1",
            "hudRevision": hud["hudRevision"],
            "captureToAssessmentNs": timing["assessmentCompletedNs"] - capture_ns,
            "assessmentToCommitNs": timing["commitCompletedNs"] - timing["assessmentCompletedNs"],
            "commitToWsDeliveryNs": published_ns - timing["commitCompletedNs"],
            "captureReceivedAt": timing["captureReceivedAt"],
            "wsPublishedAt": publish_started_at,
        }
        self.latency_trace.parent.mkdir(parents=True, exist_ok=True)
        with self.latency_trace.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")

    async def activate_target(
        self, target_id: str, expected_sha256: str, expected_list_revision: int,
    ) -> tuple[ActivatedTarget, dict[str, Any]]:
        async with self._ingest_lock:
            target = self.targets.activate(target_id, expected_sha256, expected_list_revision)
            return target, await self._activate_locked(target)

    async def activate(self, target: ActivatedTarget) -> dict[str, Any]:
        async with self._ingest_lock:
            return await self._activate_locked(target)

    async def _activate_locked(self, target: ActivatedTarget) -> dict[str, Any]:
        if self.current is None:
            hud = self.store.commit_context(
                lambda revision: _unbound_hud(
                    revision, self.runtime_instance_id, self.generation, target=target,
                ), _now(),
            )
        else:
            self.store.set_binding(_binding(self.runtime_instance_id, self.current, target))
            hud = self.coordinator.assess_commit(
                runtime_instance_id=self.runtime_instance_id, current=self.current,
                target=target, produced_at=_now(),
            )
        await self._publish_committed(hud)
        return hud

    async def ingest(self, event: dict[str, Any]) -> dict[str, Any]:
        current = self.capture.from_event(event)
        return await self.ingest_snapshot(current)

    async def ingest_snapshot(self, current: EquipmentSnapshot) -> dict[str, Any]:
        capture_received_ns = perf_counter_ns()
        capture_received_at = _now()
        async with self._ingest_lock:
            if self.current is not None and current.current_revision <= self.current.current_revision:
                raise ValueError("STALE_CURRENT_REVISION")
            self.current = current
            target = self.targets.get_active()
            if target is None:
                hud = self.store.commit_context(
                    lambda revision: _unbound_hud(
                        revision, self.runtime_instance_id, self.generation, current=current,
                    ), current.captured_at,
                )
            else:
                self.store.set_binding(_binding(self.runtime_instance_id, current, target))
                hud, timing = self.coordinator.assess_commit_timed(
                    runtime_instance_id=self.runtime_instance_id, current=current,
                    target=target, produced_at=current.captured_at,
                )
                timing.update({"captureReceivedNs": capture_received_ns,
                               "captureReceivedAt": capture_received_at})
            published_ns, publish_started_at = await self._publish_committed(hud)
            if target is not None:
                self._record_latency(
                    hud, timing, published_ns, publish_started_at,
                )
            return hud

    async def handle_control(self, command: dict[str, Any]) -> dict[str, Any] | None:
        if command.get("type") == "rulekit.snapshot":
            result = await self.snapshot_management(command.get("method", ""), command.get("params"))
            return {"correlationId": command.get("correlationId"), "result": result}
        if command.get("type") != "equipment.evidence":
            return None
        hud = await self.ingest(command.get("evidence"))
        return {"correlationId": command.get("correlationId"), "hudRevision": hud["hudRevision"]}


def create_runtime(bootstrap: dict[str, Any]) -> ProductionBackendRuntime:
    return ProductionBackendRuntime(bootstrap)

