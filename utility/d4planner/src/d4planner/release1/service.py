from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .assessment import EquipmentAssessmentService, EquipmentSnapshot
from .persistence import AssessmentBinding, DurableHudStore
from .target_repository import ActivatedTarget


class EquipmentAssessmentCoordinator:
    """Compute outside the DB lock, then fail closed if its binding became stale."""

    def __init__(
        self,
        scorer: EquipmentAssessmentService,
        store: DurableHudStore,
        publisher: Callable[[dict[str, Any]], None],
    ):
        self.scorer = scorer
        self.store = store
        self.publisher = publisher

    def assess_commit_publish(
        self,
        *,
        runtime_instance_id: str,
        current: EquipmentSnapshot,
        target: ActivatedTarget,
        produced_at: str,
    ) -> dict[str, Any]:
        policy_version = (
            target.document["assessmentPolicy"]["version"] + "+" +
            target.document["assessmentPolicy"]["weightProfile"]["profileId"]
        )
        binding = AssessmentBinding(
            runtime_instance_id, current.character_id, current.current_revision,
            target.target_id, target.content_sha256, target.selection_revision,
            policy_version,
        )
        result = self.scorer.assess(current, target)

        def payload(revision: int) -> dict[str, Any]:
            target_context = {
                "targetId": target.target_id,
                "displayName": target.display_name,
                "buildDisplayName": target.display_name,
                "contentSha256": target.content_sha256,
                "selectionRevision": target.selection_revision,
                "policyVersion": policy_version,
            }
            return {
                "schemaVersion": "d4planner-hud/v1",
                "hudRevision": revision,
                "producedAt": produced_at,
                "backend": {"runtimeInstanceId": runtime_instance_id, "generation": 1},
                "context": {
                    "state": "BOUND",
                    "character": {
                        "characterId": current.character_id,
                        "displayName": current.character_display_name,
                        "currentRevision": current.current_revision,
                    },
                    "target": target_context,
                    "binding": binding.as_dict(),
                    "selectionError": None,
                },
                "health": {
                    "capture": current.capture_health,
                    "scoreFreshness": "CURRENT" if result.score_status == "SCORED" else "NO_DATA",
                    "ruleKit": "NOT_REQUIRED",
                },
                "score": result.score_payload(),
                "equipment": list(result.rows),
                "recommendation": result.recommendation,
                "provenance": {
                    "producer": "D4PLANNER_BE",
                    "assessmentVersion": "d4planner-r1-contract/1.0.0-candidate.5",
                    "captureRevision": current.current_revision,
                    "lastObservedAt": current.captured_at,
                },
            }

        committed = self.store.commit_if_current(binding, payload, produced_at)
        # Commit is authoritative even if publish fails. S5 resync reads latest/pending.
        if self.store.is_pending(committed["hudRevision"]):
            self.publisher(committed)
            self.store.mark_published(committed["hudRevision"])
        return committed
