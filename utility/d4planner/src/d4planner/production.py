"""Concrete Release 1 Backend composition root."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .release1.assessment import EquipmentAssessmentService, EquipmentSnapshot
from .release1.capture_adapter import EquipmentCaptureAdapter
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
            target = self.runtime.targets.activate(target_id, expected_sha256, expected_list_revision)
        except TargetChanged as exc:
            raise TargetActivationError("TARGET_CHANGED", str(exc), retryable=True) from None
        except TargetError as exc:
            raise TargetActivationError(exc.code, str(exc)) from None
        hud = await self.runtime.activate(target)
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
        self.store = DurableHudStore(self.data_dir / "hud.sqlite3")
        self.capture = EquipmentCaptureAdapter()
        self.scorer = EquipmentAssessmentService()
        self.coordinator = EquipmentAssessmentCoordinator(self.scorer, self.store, lambda _: None)
        self.current: EquipmentSnapshot | None = None
        self.hub: HudHub | None = None
        self.server: D4PlannerWebSocketServer | None = None

    async def start(self) -> dict[str, Any]:
        if self.rulekit is None:
            self.rulekit = RuleKitRuntimeService.from_environment()
        rulekit_health = await self.rulekit.start()
        try:
            target = self.targets.get_active()
            initial = self.store.commit_context(
                lambda revision: _unbound_hud(
                    revision, self.runtime_instance_id, self.generation,
                    target=target, rulekit_state="READY",
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
            return {
                "wsEndpoint": {"host": endpoint["host"], "port": self.server.port},
                "health": {
                    "durableState": "READY", "targetRepository": "READY",
                    "targetJsonCount": len(self.targets.list().entries),
                    "wsTransport": "READY", "ruleKitWorker": "READY",
                    "ruleKitGeneration": rulekit_health["workerGeneration"],
                    "equipmentCapture": capture_state,
                },
            }
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self.server is not None:
            await self.server.close()
            self.server = None
        if self.rulekit is not None:
            await self.rulekit.stop()

    async def _publish_committed(self, hud: dict[str, Any]) -> None:
        if self.hub is None:
            raise RuntimeError("HUD hub is not started")
        await self.hub.publish_after_commit(hud)
        self.store.mark_published(hud["hudRevision"])

    async def activate(self, target: ActivatedTarget) -> dict[str, Any]:
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
            hud = self.coordinator.assess_commit(
                runtime_instance_id=self.runtime_instance_id, current=current,
                target=target, produced_at=current.captured_at,
            )
        await self._publish_committed(hud)
        return hud

    async def handle_control(self, command: dict[str, Any]) -> dict[str, Any] | None:
        if command.get("type") != "equipment.evidence":
            return None
        hud = await self.ingest(command.get("evidence"))
        return {"correlationId": command.get("correlationId"), "hudRevision": hud["hudRevision"]}


def create_runtime(bootstrap: dict[str, Any]) -> ProductionBackendRuntime:
    return ProductionBackendRuntime(bootstrap)

