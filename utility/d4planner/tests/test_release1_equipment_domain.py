from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from d4planner.release1.assessment import (
    EquipmentAssessmentService,
    EquipmentSnapshot,
    ObservedEntity,
    ObservedItem,
    ObservedValue,
    _parameter_passes,
)
from d4planner.release1.capture_adapter import (
    EquipmentCaptureAdapter, EquipmentEvidenceError, RepositoryEquipmentCaptureAdapter,
)
from d4planner.release1.persistence import AssessmentBinding, DurableHudStore, StaleAssessment
from d4planner.release1.service import EquipmentAssessmentCoordinator
from d4planner.release1.target_repository import (
    ActivatedTarget,
    TargetChanged,
    TargetInvalid,
    TargetNotFound,
    TargetRepository,
    TargetValidator,
)
from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import (
    EquipmentRepository, EquipmentRepositoryIncompatible,
    EquipmentRepositoryTransient, EquipmentRepositoryUnavailable,
    ReadOnlyEquipmentRepository,
)


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "utility/d4planner/contracts/release1/v1"
TARGET_FIXTURE = CONTRACT / "fixtures/target.valid.synthetic.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def validator() -> TargetValidator:
    return TargetValidator.from_contract_tree(ROOT)


def write_target(folder: Path, name: str = "target.json", mutate=None) -> Path:
    document = load_json(TARGET_FIXTURE)
    if mutate:
        mutate(document)
    path = folder / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def activate(folder: Path, validator: TargetValidator) -> ActivatedTarget:
    repo = TargetRepository(folder, folder.parent / "state/selection.json", validator)
    listing = repo.list()
    valid = next(entry for entry in listing.entries if entry.validation == "VALID")
    return repo.activate(valid.target_id, valid.content_sha256, listing.revision)


def entity(kind, group, entity_id, values, *, occurrence=0):
    return ObservedEntity(kind, group, entity_id, occurrence, entity_id, tuple(values))


def number(value, unit):
    return ObservedValue("NUMBER", value, unit)


def current_snapshot(*, attack=9, ranks=2, damage=10, targets=2, ring=6, complete=True):
    gloves_entities = tuple(value for value in (
        entity("AFFIX", "AFFIXES", "attack-speed", (number(attack, "PERCENT"),)) if attack is not None else None,
        entity("AFFIX", "AFFIXES", "core-skill-ranks", (number(ranks, "RANK"),)) if ranks is not None else None,
        entity("EFFECT", "ASPECTS", "charge-bolt-core-effect", (
            number(damage, "PERCENT"), number(targets, "FLAT")
        )) if damage is not None else None,
    ) if value is not None)
    items = (
        ObservedItem("gloves", "different-current-gloves", "Current Gloves (name need not match)",
                     "2026-10-25T10:00:00Z", entities=gloves_entities),
        ObservedItem("ring-1", "different-current-ring", "Current Ring",
                     "2026-10-25T10:00:00Z", entities=(
                         entity("AFFIX", "AFFIXES", "resource-cost-reduction", (number(ring, "PERCENT"),)),
                     )),
    )
    evidence = {
        "gloves": frozenset({"COMPLETE_SLOT"}) if complete else frozenset({"PRESENT_VALUE"}),
        "ring-1": frozenset({"COMPLETE_SLOT"}) if complete else frozenset(),
    }
    return EquipmentSnapshot(
        "character-a", "Synthetic Character", 41, "2026-10-25T10:00:00Z",
        items, evidence,
    )


def test_target_repository_lists_valid_and_invalid_and_rechecks_hash(tmp_path, validator):
    folder = tmp_path / "targets"
    folder.mkdir()
    write_target(folder)
    (folder / "broken.json").write_text("{", encoding="utf-8")
    repo = TargetRepository(folder, tmp_path / "state/selection.json", validator)
    listing = repo.list()
    assert sorted(entry.validation for entry in listing.entries) == ["INVALID", "VALID"]
    valid = next(entry for entry in listing.entries if entry.validation == "VALID")

    write_target(folder, mutate=lambda doc: doc.update(displayName="Changed bytes"))
    with pytest.raises(TargetChanged, match="TARGET_CHANGED"):
        repo.activate(valid.target_id, valid.content_sha256, listing.revision)


def test_target_repository_rejects_deleted_invalid_duplicate_and_unsafe_ids(tmp_path, validator):
    folder = tmp_path / "targets"
    folder.mkdir()
    first = write_target(folder, "a.json")
    write_target(folder, "b.json")
    repo = TargetRepository(folder, tmp_path / "selection.json", validator)
    duplicate_listing = repo.list()
    assert all(entry.validation == "INVALID" for entry in duplicate_listing.entries)
    with pytest.raises(TargetInvalid):
        repo.activate("synthetic-charge-bolt", duplicate_listing.entries[0].content_sha256,
                      duplicate_listing.revision)

    first.unlink()
    (folder / "b.json").unlink()
    write_target(folder)
    listing = repo.list()
    valid = next(entry for entry in listing.entries if entry.validation == "VALID")
    (folder / "target.json").unlink()
    with pytest.raises(TargetNotFound):
        repo.activate(valid.target_id, valid.content_sha256, listing.revision)
    with pytest.raises(TargetNotFound):
        repo.activate("../../secret", valid.content_sha256, listing.revision)


def test_target_repository_rejects_symlink_and_bounded_file_count(tmp_path, validator):
    folder = tmp_path / "targets"
    folder.mkdir()
    outside = write_target(tmp_path, "outside.json")
    (folder / "linked.json").symlink_to(outside)
    repo = TargetRepository(folder, tmp_path / "selection.json", validator, max_files=1)
    with pytest.raises(TargetInvalid, match="UNSAFE_TARGET_PATH"):
        repo.list()
    write_target(folder, "real.json", mutate=lambda document: document.update(targetId="target-two"))
    with pytest.raises(TargetInvalid, match="TARGET_FILE_LIMIT_EXCEEDED"):
        repo.list()


def test_target_selection_persists_but_changed_or_missing_target_does_not_reactivate(tmp_path, validator):
    folder = tmp_path / "targets"
    folder.mkdir()
    path = write_target(folder)
    state = tmp_path / "state/selection.json"
    repo = TargetRepository(folder, state, validator)
    listing = repo.list()
    valid = listing.entries[0]
    activated = repo.activate(valid.target_id, valid.content_sha256, listing.revision)
    assert activated.selection_revision == 1

    restarted = TargetRepository(folder, state, validator)
    assert restarted.get_active().content_sha256 == valid.content_sha256
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert restarted.get_active() is None
    path.unlink()
    assert restarted.get_active() is None


def test_get_active_revalidation_does_not_invalidate_list_selection_revision(tmp_path, validator):
    folder = tmp_path / "targets"
    folder.mkdir()
    write_target(folder)
    repo = TargetRepository(folder, tmp_path / "state/selection.json", validator)
    listing = repo.list()
    valid = listing.entries[0]
    first = repo.activate(valid.target_id, valid.content_sha256, listing.revision)

    assert repo.get_active() == first
    # Interleaved health/HUD reads must not manufacture TARGET_LIST_CHANGED.
    second = repo.activate(valid.target_id, valid.content_sha256, listing.revision)
    assert second.selection_revision == first.selection_revision + 1


def test_target_semantics_reject_duplicate_criterion_and_bad_parameter_link(validator):
    duplicate = load_json(TARGET_FIXTURE)
    duplicate["assessmentPolicy"]["criteria"].append(
        copy.deepcopy(duplicate["assessmentPolicy"]["criteria"][0])
    )
    with pytest.raises(TargetInvalid, match="DUPLICATE_CRITERION"):
        validator.validate(duplicate)
    bad_link = load_json(TARGET_FIXTURE)
    bad_link["assessmentPolicy"]["criteria"][0]["parameters"][0]["index"] = 99
    with pytest.raises(TargetInvalid, match="PARAMETER_INDEX_MISSING"):
        validator.validate(bad_link)
    duplicate_order = load_json(TARGET_FIXTURE)
    duplicate_order["assessmentPolicy"]["criteria"][1]["targetOrder"] = 0
    with pytest.raises(TargetInvalid, match="DUPLICATE_TARGET_ORDER"):
        validator.validate(duplicate_order)
    duplicate_index = load_json(TARGET_FIXTURE)
    duplicate_index["assessmentPolicy"]["criteria"][2]["parameters"][1]["index"] = 0
    with pytest.raises(TargetInvalid, match="DUPLICATE_PARAMETER_INDEX"):
        validator.validate(duplicate_index)


def test_score_all_pass_over_target_and_item_names_are_not_identity(tmp_path, validator):
    folder = tmp_path / "targets"; folder.mkdir(); write_target(folder)
    target = activate(folder, validator)
    result = EquipmentAssessmentService().assess(current_snapshot(attack=99), target)
    assert (result.score_status, result.score, result.passed_weight, result.evaluable_weight) == (
        "SCORED", 100, 8, 8,
    )
    assert (result.items_passing, result.items_targeted, result.fail_issues, result.warnings) == (2, 2, 0, 0)
    assert {row["currentItem"]["source"] for row in result.rows} == {"CAPTURE"}
    assert result.recommendation is None

    current = current_snapshot(attack=99)
    first = current.items[0]
    recorded = EquipmentSnapshot(
        current.character_id, current.character_display_name, current.current_revision,
        current.captured_at,
        (ObservedItem(
            first.slot_id, first.item_id, first.display_name, first.observed_at,
            "RECORDED_SYNTHETIC_E2E_INPUT", first.entities,
        ), *current.items[1:]),
        current.slot_evidence, current.capture_health,
    )
    recorded_result = EquipmentAssessmentService().assess(recorded, target)
    assert recorded_result.rows[0]["currentItem"]["source"] == "MATERIALIZED_CAPTURE"


def test_partial_no_data_all_fail_low_roll_and_non_core_warn(tmp_path, validator):
    folder = tmp_path / "targets"; folder.mkdir(); write_target(folder)
    target = activate(folder, validator)
    scorer = EquipmentAssessmentService()

    partial = current_snapshot(ranks=None, damage=None, complete=False)
    result = scorer.assess(partial, target)
    assert (result.score, result.passed_weight, result.evaluable_weight) == (100, 4, 4)
    assert (result.evaluated_criteria, result.total_criteria, result.items_passing) == (2, 4, 1)

    no_data = EquipmentSnapshot("c", "C", 1, "2026-10-25T10:00:00Z", (), {})
    result = scorer.assess(no_data, target)
    assert (result.score_status, result.score, result.evaluable_weight) == ("NO_DATA", None, 0)

    confirmed_missing = EquipmentSnapshot(
        "c", "C", 2, "2026-10-25T10:00:00Z", (),
        {"gloves": frozenset({"COMPLETE_SLOT"}), "ring-1": frozenset({"COMPLETE_SLOT"})},
    )
    result = scorer.assess(confirmed_missing, target)
    assert (result.score, result.fail_issues, result.warnings) == (0, 2, 2)

    low = scorer.assess(current_snapshot(attack=7, ring=7), target)
    assert low.score == pytest.approx(50)
    assert low.fail_issues == 0 and low.warnings == 2
    assert low.recommendation["criterionIds"] == ["gloves.attack-speed"]


def test_typed_mismatch_is_unknown_and_non_equipment_does_not_change_score(tmp_path, validator):
    folder = tmp_path / "targets"; folder.mkdir(); write_target(folder)
    target = activate(folder, validator)
    current = current_snapshot()
    bad_entity = entity("AFFIX", "AFFIXES", "attack-speed", (
        ObservedValue("BOOLEAN", True, "PERCENT"),
    ))
    gloves = current.items[0]
    changed = EquipmentSnapshot(
        current.character_id, current.character_display_name, current.current_revision,
        current.captured_at,
        (ObservedItem(gloves.slot_id, gloves.item_id, gloves.display_name, gloves.observed_at,
                      entities=(bad_entity,) + gloves.entities[1:]), current.items[1]),
        current.slot_evidence,
    )
    result = EquipmentAssessmentService().assess(changed, target)
    attack = result.rows[0]["comparisons"][0]
    assert attack["status"] == "UNKNOWN"
    assert result.evaluable_weight == 5

    modified = copy.deepcopy(target.document)
    modified["canonicalBuild"]["skills"]["allocations"][0]["rank"] = 99
    modified["canonicalBuild"]["paragon"]["boards"][0]["rotation"] = 3
    other = ActivatedTarget(target.target_id, target.display_name, target.content_sha256,
                            target.selection_revision, modified)
    assert EquipmentAssessmentService().assess(current, other).score == 100


@pytest.mark.parametrize(("comparator", "expected", "actual", "outcome"), [
    ("AT_LEAST", {"type": "NUMBER", "value": 8}, number(8, "PERCENT"), True),
    ("AT_LEAST", {"type": "NUMBER", "value": 8}, number(7, "PERCENT"), False),
    ("AT_MOST", {"type": "NUMBER", "value": 4}, number(3, "PERCENT"), True),
    ("BETWEEN", {"type": "NUMBER_RANGE", "minimum": 2, "maximum": 4}, number(5, "PERCENT"), False),
    ("EQUAL", {"type": "TEXT", "value": "enabled"}, ObservedValue("TEXT", "enabled"), True),
    ("EQUAL", {"type": "NUMBER", "value": 1}, ObservedValue("NUMBER", True), None),
    ("PRESENT", {"type": "PRESENCE", "value": True}, ObservedValue("BOOLEAN", True), True),
    ("PRESENT", {"type": "PRESENCE", "value": True}, None, None),
])
def test_raw_parameter_comparators(comparator, expected, actual, outcome):
    parameter = {"comparator": comparator, "expected": expected, "unit": "PERCENT"}
    if comparator in {"EQUAL", "PRESENT"}:
        parameter["unit"] = "NONE"
    assert _parameter_passes(parameter, actual) is outcome


def test_durable_commit_rejects_late_binding_is_idempotent_and_recovers_publish_gap(tmp_path, validator):
    folder = tmp_path / "targets"; folder.mkdir(); write_target(folder)
    target = activate(folder, validator)
    current = current_snapshot()
    store = DurableHudStore(tmp_path / "state/hud.db")
    policy = target.document["assessmentPolicy"]
    binding = AssessmentBinding(
        "runtime-a", current.character_id, current.current_revision,
        target.target_id, target.content_sha256, target.selection_revision,
        policy["version"] + "+" + policy["weightProfile"]["profileId"],
    )
    store.set_binding(binding)
    published = []
    coordinator = EquipmentAssessmentCoordinator(
        EquipmentAssessmentService(), store, lambda payload: published.append(payload["hudRevision"])
    )
    first = coordinator.assess_commit_publish(
        runtime_instance_id="runtime-a", current=current, target=target,
        produced_at="2026-10-25T10:00:01Z",
    )
    second = coordinator.assess_commit_publish(
        runtime_instance_id="runtime-a", current=current, target=target,
        produced_at="2026-10-25T10:00:02Z",
    )
    assert second == store.latest() and first["hudRevision"] == second["hudRevision"] == 0
    assert published == [0]
    assert store.pending_publish() == ()

    stale = copy.copy(binding)
    store.set_binding(AssessmentBinding(
        "runtime-a", current.character_id, 42, target.target_id,
        target.content_sha256, target.selection_revision, binding.policy_version,
    ))
    assert store.latest() is None
    assert store.pending_publish() == ()
    with pytest.raises(StaleAssessment):
        store.commit_if_current(stale, lambda revision: {"hudRevision": revision}, "t")

    store.set_binding(binding)
    failing = EquipmentAssessmentCoordinator(
        EquipmentAssessmentService(), DurableHudStore(tmp_path / "state/gap.db"),
        lambda _payload: (_ for _ in ()).throw(OSError("socket unavailable")),
    )
    failing.store.set_binding(binding)
    with pytest.raises(OSError, match="socket unavailable"):
        failing.assess_commit_publish(
            runtime_instance_id="runtime-a", current=current, target=target,
            produced_at="2026-10-25T10:00:03Z",
        )
    assert failing.store.latest()["hudRevision"] == 0
    assert len(failing.store.pending_publish()) == 1


def test_committed_hud_validates_closed_schema(tmp_path, validator):
    folder = tmp_path / "targets"; folder.mkdir(); write_target(folder)
    target = activate(folder, validator)
    current = current_snapshot()
    store = DurableHudStore(tmp_path / "hud.db")
    policy = target.document["assessmentPolicy"]
    store.set_binding(AssessmentBinding(
        "runtime-a", current.character_id, current.current_revision,
        target.target_id, target.content_sha256, target.selection_revision,
        policy["version"] + "+" + policy["weightProfile"]["profileId"],
    ))
    hud = EquipmentAssessmentCoordinator(
        EquipmentAssessmentService(), store, lambda _payload: None
    ).assess_commit_publish(
        runtime_instance_id="runtime-a", current=current, target=target,
        produced_at="2026-10-25T10:00:01Z",
    )
    schema = load_json(CONTRACT / "schemas/hud.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(hud)


def test_assessment_coordinator_reports_ordered_measurement_boundaries(tmp_path, validator):
    folder = tmp_path / "targets"; folder.mkdir(); write_target(folder)
    target = activate(folder, validator); current = current_snapshot()
    store = DurableHudStore(tmp_path / "timed.db")
    store.set_binding(AssessmentBinding(
        "runtime-a", current.character_id, current.current_revision,
        target.target_id, target.content_sha256, target.selection_revision,
        target.document["assessmentPolicy"]["version"] + "+" +
        target.document["assessmentPolicy"]["weightProfile"]["profileId"],
    ))
    hud, timing = EquipmentAssessmentCoordinator(
        EquipmentAssessmentService(), store, lambda _payload: None,
    ).assess_commit_timed(
        runtime_instance_id="runtime-a", current=current, target=target,
        produced_at="2026-10-25T10:00:01Z",
    )
    assert hud["hudRevision"] == 0
    assert timing["assessmentStartedNs"] <= timing["assessmentCompletedNs"] <= timing["commitCompletedNs"]


def test_store_lock_fails_closed_and_restart_preserves_latest(tmp_path):
    path = tmp_path / "hud.db"
    store = DurableHudStore(path, timeout_seconds=0.01)
    binding = AssessmentBinding("runtime", "character", 1, "target-one", "a" * 64, 1, "policy")
    store.set_binding(binding)
    committed = store.commit_if_current(binding, lambda revision: {"hudRevision": revision}, "t1")
    lock = sqlite3.connect(path)
    try:
        lock.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            store.set_binding(AssessmentBinding(
                "runtime", "character", 2, "target-one", "a" * 64, 1, "policy"
            ))
    finally:
        lock.rollback()
        lock.close()
    restarted = DurableHudStore(path)
    assert restarted.latest() == committed
    assert restarted.current_binding() == binding.as_dict()


def test_store_refuses_newer_schema_without_wiping_data(tmp_path):
    path = tmp_path / "newer.db"
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE TABLE schema_meta(component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
        db.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
        db.execute("INSERT INTO schema_meta VALUES('release1-hud', 99)")
        db.execute("INSERT INTO sentinel VALUES('keep-me')")
        db.commit()
    finally:
        db.close()
    with pytest.raises(RuntimeError, match="HUD_STORE_SCHEMA_NEWER_THAN_RUNTIME"):
        DurableHudStore(path)
    with sqlite3.connect(path) as reopened:
        assert reopened.execute("SELECT value FROM sentinel").fetchone()[0] == "keep-me"


def test_store_commits_authoritative_unbound_context_for_restart_and_publish_recovery(tmp_path):
    store = DurableHudStore(tmp_path / "hud.db")
    payload = store.commit_context(
        lambda revision: {"hudRevision": revision, "context": {"state": "TARGET_ONLY"}},
        "2026-10-26T03:00:00Z",
    )
    assert payload["hudRevision"] == 0
    assert store.latest_authoritative() == payload
    assert store.pending_authoritative() == (payload,)
    store.mark_published(0)
    assert store.pending_authoritative() == ()
    assert DurableHudStore(tmp_path / "hud.db").latest_authoritative() == payload


def test_capture_session_change_cannot_complete_previous_sessions_partial_item(tmp_path):
    repository = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repository)
    old_session = ["Head", "EQUIPPED", "OLD CHARACTER HELM"]
    for sequence, value in enumerate(old_session, 1):
        projector.consume({
            "eventSeq": sequence, "type": "speech.raw", "timestamp": f"old-{sequence}",
            "sessionId": "old-session", "data": {"text": value},
        })
    for sequence, value in enumerate(["Rare Helm", "850 Item Power"], 1):
        projector.consume({
            "eventSeq": sequence, "type": "speech.raw", "timestamp": f"new-{sequence}",
            "sessionId": "new-session", "data": {"text": value},
        })
    assert repository.list_equipment() == []


def test_versioned_capture_adapter_preserves_typed_identity_and_partial_evidence():
    event = {
        "schemaVersion": "d4planner-equipment-evidence/v1",
        "characterId": "character-a", "characterDisplayName": "Recorded Character",
        "currentRevision": 42, "capturedAt": "2026-10-26T03:00:00Z",
        "captureHealth": "HEALTHY",
        "slots": [{
            "slotId": "gloves", "presence": "OBSERVED", "evidence": ["PRESENT_VALUE"],
            "item": {
                "itemId": "captured-gloves", "displayName": "Recorded Gloves",
                "observedAt": "2026-10-26T03:00:00Z", "source": "RECORDED_CAPTURE",
                "entities": [{
                    "kind": "AFFIX", "group": "AFFIXES", "entityId": "attack-speed",
                    "occurrence": 0, "label": "Attack Speed", "values": [{
                        "type": "NUMBER", "value": 9, "unit": "PERCENT", "evidence": "OBSERVED",
                    }],
                }],
            },
        }, {
            "slotId": "ring-1", "presence": "UNKNOWN", "evidence": [], "item": None,
        }],
    }
    snapshot = EquipmentCaptureAdapter().from_event(event)
    assert snapshot.current_revision == 42
    assert snapshot.items[0].entities[0].entity_id == "attack-speed"
    assert snapshot.slot_evidence["gloves"] == frozenset({"PRESENT_VALUE"})
    assert snapshot.slot_evidence["ring-1"] == frozenset()
    broken = copy.deepcopy(event); broken["slots"][0]["item"]["entities"][0]["entityId"] = ""
    with pytest.raises(EquipmentEvidenceError, match="stable entityId"):
        EquipmentCaptureAdapter().from_event(broken)


def test_legacy_capture_repository_never_fuzzy_maps_human_labels(tmp_path):
    repository = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repository)
    lines = ["Head", "EQUIPPED", "RECORDED HELM", "Rare Helm", "850 Item Power", "Unequip"]
    for sequence, text in enumerate(lines, 1):
        projector.consume({
            "eventSeq": sequence, "type": "speech.raw", "timestamp": f"2026-10-26T03:00:0{sequence}Z",
            "sessionId": "recorded-session", "data": {"text": text},
        })
    snapshot = RepositoryEquipmentCaptureAdapter(repository).snapshot(
        character_id="character-a", character_display_name="Recorded Character", current_revision=1,
    )
    assert len(snapshot.items) == 1
    assert snapshot.items[0].display_name == "RECORDED HELM"
    assert snapshot.items[0].entities == ()
    assert snapshot.slot_evidence["helm"] == frozenset({"PRESENT_VALUE"})
    assert repository.projection_revision() == (
        1, "recorded-session", 6, "2026-10-26T03:00:06Z",
    )


def test_projection_revision_changes_only_for_equipment_materialization(tmp_path):
    repository = EquipmentRepository(tmp_path / "character.db")
    repository.commit_event(
        session_id="session-a", event_seq=1, updated_at="2026-10-26T03:00:01Z",
        observation=None,
    )
    assert repository.projection_revision() is None
    repository.commit_event(
        session_id="session-a", event_seq=2, updated_at="2026-10-26T03:00:02Z",
        observation=None, empty_slot_family="helm",
    )
    assert repository.projection_revision() == (1, "session-a", 2, "2026-10-26T03:00:02Z")
    repository.commit_event(
        session_id="session-b", event_seq=1, updated_at="2026-10-26T03:00:03Z",
        observation=None, remove_item_fingerprint="owned-ring",
    )
    assert repository.projection_revision() == (2, "session-b", 1, "2026-10-26T03:00:03Z")


def test_read_only_projection_reads_without_schema_or_database_mutation(tmp_path):
    path = tmp_path / "producer.db"
    writer = EquipmentRepository(path)
    writer.commit_event(
        session_id="session-a", event_seq=1, updated_at="2026-10-26T03:00:01Z",
        observation=None, empty_slot_family="helm",
    )
    before_bytes = path.read_bytes()
    with sqlite3.connect(path) as db:
        before_schema = tuple(db.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
        ))

    reader = ReadOnlyEquipmentRepository(path)
    view = reader.projection_snapshot()
    assert view.revision == (1, "session-a", 1, "2026-10-26T03:00:01Z")
    assert view.rows == ()
    with reader._connect() as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("INSERT INTO equipment_projection_revision VALUES(2,2,'x',2,'x')")

    assert path.read_bytes() == before_bytes
    with sqlite3.connect(path) as db:
        assert tuple(db.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
        )) == before_schema


def test_read_only_projection_is_consistent_during_concurrent_writer_commit(tmp_path):
    path = tmp_path / "producer.db"
    writer = EquipmentRepository(path)
    writer.commit_event(
        session_id="session-a", event_seq=1, updated_at="2026-10-26T03:00:01Z",
        observation=None, empty_slot_family="helm",
    )
    reader = ReadOnlyEquipmentRepository(path)
    write_connection = sqlite3.connect(path)
    try:
        write_connection.execute("BEGIN IMMEDIATE")
        write_connection.execute(
            "UPDATE equipment_projection_revision SET revision=2,event_seq=2 WHERE singleton=1"
        )
        # An uncommitted producer revision is never paired with rows from that revision.
        assert reader.projection_snapshot().revision[0] == 1
        write_connection.commit()
        assert reader.projection_snapshot().revision[0] == 2
    finally:
        write_connection.close()


def test_read_only_projection_fails_closed_for_missing_invalid_and_locked_db(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(EquipmentRepositoryUnavailable, match="MISSING"):
        ReadOnlyEquipmentRepository(missing)
    assert not missing.exists()

    invalid = tmp_path / "invalid.db"
    sqlite3.connect(invalid).close()
    with pytest.raises(EquipmentRepositoryIncompatible, match="SCHEMA_INCOMPATIBLE"):
        ReadOnlyEquipmentRepository(invalid).projection_snapshot()

    locked = tmp_path / "locked.db"
    writer = EquipmentRepository(locked)
    with sqlite3.connect(locked) as lock:
        lock.execute("PRAGMA journal_mode=DELETE")
        lock.execute("BEGIN EXCLUSIVE")
        with pytest.raises(EquipmentRepositoryTransient, match="BUSY"):
            ReadOnlyEquipmentRepository(locked, timeout_seconds=0.01).projection_snapshot()


def test_repository_ring_identity_requires_verified_physical_slot(tmp_path):
    path = tmp_path / "rings.db"
    writer = EquipmentRepository(path)
    item = json.dumps({"rarity": "RARE", "affixes": [], "effects_raw": []})
    with writer._connect() as db:
        for index, fingerprint, observed in (
            (1, "ring-left", "2026-10-26T03:00:02Z"),
            (2, "ring-right", "2026-10-26T03:00:01Z"),
        ):
            db.execute(
                "INSERT INTO equipment_current(slot_family,slot_index,item_name,item_type,item_power,item_json,observed_at,source_session_id,source_event_seq_start,source_event_seq_end,confidence,item_fingerprint) VALUES('ring',?,?,?,?,?,?,?,?,?,?,?)",
                (index, fingerprint, "Ring", 800, item, observed, "s", 1, 1, "HIGH", fingerprint),
            )
    adapter = RepositoryEquipmentCaptureAdapter(writer)
    first = adapter.snapshot(
        character_id="c", character_display_name="C", current_revision=1,
    )
    assert {item.item_id: item.slot_id for item in first.items} == {
        "ring-left": "ring-1", "ring-right": "ring-2",
    }

    with writer._connect() as db:
        db.execute("UPDATE equipment_current SET observed_at='2026-10-26T04:00:00Z' WHERE item_fingerprint='ring-right'")
    reordered = adapter.snapshot(
        character_id="c", character_display_name="C", current_revision=2,
    )
    assert {item.item_id: item.slot_id for item in reordered.items} == {
        "ring-left": "ring-1", "ring-right": "ring-2",
    }

    with writer._connect() as db:
        db.execute("UPDATE equipment_current SET slot_index=NULL")
    unknown = adapter.snapshot(
        character_id="c", character_display_name="C", current_revision=3,
    )
    assert all(item.slot_id.startswith("unresolved-ring:") for item in unknown.items)
    assert not ({"ring-1", "ring-2"} & set(unknown.slot_evidence))


@pytest.mark.parametrize("fault", ["empty", "unreadable", "oversized", "deleted", "symlink", "shrunk", "grew"])
def test_list_content_failure_is_operation_error_preserves_selection(tmp_path, validator, monkeypatch, fault):
    folder = tmp_path / "targets"
    folder.mkdir()
    good = write_target(folder)
    repo = TargetRepository(folder, tmp_path / "selection.json", validator)
    listing = repo.list()
    entry = listing.entries[0]
    repo.activate(entry.target_id, entry.content_sha256, listing.revision)
    saved = repo.selection_state.read_bytes()
    bad = folder / "bad.json"
    bad.write_bytes(b"{}")
    if fault == "empty":
        bad.write_bytes(b"")
    elif fault == "oversized":
        bad.write_bytes(b"x" * (repo.max_file_bytes + 1))
    elif fault == "symlink":
        bad.unlink()
        bad.symlink_to(good)
    else:
        original = repo._read_candidate
        def read(path):
            if path == bad:
                if fault == "deleted":
                    bad.unlink()
                elif fault == "unreadable":
                    raise PermissionError("private path must not leak")
                else:
                    # File changed after stat, before actual content read.
                    original_open = Path.open
                    def changed_open(path, *args, **kwargs):
                        if path == bad:
                            with original_open(path, "wb") as stream:
                                stream.write(b"" if fault == "shrunk" else b"x" * (repo.max_file_bytes + 1))
                        return original_open(path, *args, **kwargs)
                    monkeypatch.setattr(Path, "open", changed_open)
            return original(path)
        monkeypatch.setattr(repo, "_read_candidate", read)
    with pytest.raises(TargetInvalid) as error:
        repo.list()
    assert error.value.code == "TARGET_INVALID"
    assert "private path" not in str(error.value)
    assert repo.selection_state.read_bytes() == saved
    assert repo._list_revision == listing.revision
    # A failed refresh does not replace the last successful candidate set.
    assert repo.activate(entry.target_id, entry.content_sha256, listing.revision).target_id == entry.target_id


def test_real_listing_wire_schema_and_content_hashes(tmp_path, validator):
    good = write_target(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"{")
    repo = TargetRepository(tmp_path, tmp_path / "state/selection.json", validator)
    listing = repo.list()
    wire = {"protocolVersion": "d4planner-ws/v1", "messageId": "list-1",
            "type": "target.list.result", "correlationId": "request-1",
            "backendGeneration": 1, "listRevision": listing.revision,
            "targets": [{"targetId": e.target_id, "displayName": e.display_name,
                         "contentSha256": e.content_sha256, "byteLength": e.byte_length,
                         "validation": e.validation, "errorCodes": list(e.error_codes)}
                        for e in listing.entries]}
    schema = load_json(CONTRACT / "schemas/command.schema.json")
    for entry in wire["targets"]:
        Draft202012Validator({"$ref": "#/$defs/targetEntry", "$defs": schema["$defs"]}).validate(entry)
    for entry in listing.entries:
        data = (good if entry.validation == "VALID" else bad).read_bytes()
        assert (entry.content_sha256, entry.byte_length) == (sha256(data).hexdigest(), len(data))
        if entry.validation == "INVALID":
            with pytest.raises(TargetInvalid):
                repo.activate(entry.target_id, entry.content_sha256, listing.revision)


# Independent truth table: entity presence is not numeric parameter presence.
@pytest.mark.parametrize("mode,tokens,values,core,expected", [
    ("presence", (), (number(9, "PERCENT"),), True, "PASS"),
    ("presence", (), (), True, "PASS"),
    ("wrong-identity", (), (), True, "UNKNOWN"),
    ("wrong-identity", ("COMPLETE_CATEGORY",), (), True, "FAIL"),
    ("presence", (), None, True, "UNKNOWN"),
    ("presence", ("PRESENT_VALUE",), None, True, "UNKNOWN"),
    ("presence", ("COMPLETE_CATEGORY",), None, True, "FAIL"),
    ("presence", ("COMPLETE_SLOT",), None, False, "WARN"),
    ("numeric", (), (), True, "UNKNOWN"),
    ("numeric", ("COMPLETE_SLOT",), (), True, "UNKNOWN"),
    ("numeric", (), (number(7, "PERCENT"),), True, "WARN"),
    ("numeric", (), (number(7, "PERCENT"),), False, "WARN"),
    ("numeric", (), (number(9, "FLAT"),), True, "UNKNOWN"),
    ("equality", (), (ObservedValue("BOOLEAN", True),), True, "UNKNOWN"),
    ("multi", (), (number(10, "PERCENT"),), True, "UNKNOWN"),
    ("multi", ("COMPLETE_SLOT",), (number(10, "PERCENT"),), True, "UNKNOWN"),
    ("multi", (), (number(10, "PERCENT"), number(2, "FLAT")), True, "PASS"),
])
def test_criterion_presence_completeness_truth_and_hud_schema(tmp_path, validator, mode, tokens, values, core, expected):
    document = load_json(TARGET_FIXTURE)
    criterion = copy.deepcopy(document["assessmentPolicy"]["criteria"][2 if mode == "multi" else 0])
    criterion.update(core=core, weightClass="CORE" if core else "NON_CORE",
                     evidenceRequirement="COMPLETE_CATEGORY")
    if mode in {"presence", "wrong-identity"}:
        criterion["parameters"] = [{"parameterId": "presence", "index": 0,
            "comparator": "PRESENT", "unit": "NONE", "expected": {"type": "PRESENCE", "value": True}}]
    if mode == "equality":
        criterion["parameters"][0].update(comparator="EQUAL", unit="NONE")
    document["assessmentPolicy"]["criteria"] = [criterion]
    validator.validate(document)
    target = ActivatedTarget(document["targetId"], document["displayName"], "a" * 64, 1, document)
    entities = [] if values is None else [{"kind": criterion["kind"], "group": criterion["source"]["group"],
        "entityId": "unrelated-entity" if mode == "wrong-identity" else criterion["entityId"], "occurrence": 0, "label": "Synthetic observed entity",
        "values": [{**v.as_dict(), "evidence": "OBSERVED"} for v in values]}]
    current = EquipmentCaptureAdapter().from_event({
        "schemaVersion": "d4planner-equipment-evidence/v1", "characterId": "synthetic-character",
        "characterDisplayName": "Synthetic Character", "currentRevision": 1,
        "capturedAt": "2026-10-25T10:00:00Z", "captureHealth": "HEALTHY",
        "slots": [{"slotId": "gloves", "presence": "OBSERVED", "evidence": list(tokens),
                   "item": {"itemId": "observed-gloves", "displayName": "Synthetic Gloves",
                            "observedAt": "2026-10-25T10:00:00Z", "entities": entities}}]})
    result = EquipmentAssessmentService().assess(current, target)
    comparison = result.rows[0]["comparisons"][0]
    assert comparison["status"] == expected
    if mode == "presence" and expected == "PASS":
        assert comparison["parameters"][0]["actual"] == {"type": "BOOLEAN", "value": True, "unit": "NONE"}
    if mode == "multi" and expected == "UNKNOWN":
        assert comparison["parameters"][1]["evidence"] == "INCOMPLETE"
    weight = 3 if core else 1
    assert result.score == (None if expected == "UNKNOWN" else 100 if expected == "PASS" else 0)
    assert result.score_status == ("NO_DATA" if expected == "UNKNOWN" else "SCORED")
    assert result.evaluable_weight == (0 if expected == "UNKNOWN" else weight)
    assert result.passed_weight == (weight if expected == "PASS" else 0)
    assert (result.fail_issues, result.warnings) == (int(expected == "FAIL"), int(expected == "WARN"))
    assert (result.items_passing, result.items_targeted) == (int(expected == "PASS"), 1)
    assert result.total_criteria == 1
    assert (result.recommendation is None) == (expected in {"PASS", "UNKNOWN"})
    if result.recommendation:
        assert result.recommendation["criterionIds"] == [criterion["criterionId"]]
        assert result.recommendation["action"] == ("REPLACE" if expected == "FAIL" else "IMPROVE_ROLL")
    store = DurableHudStore(tmp_path / "hud.db")
    policy = document["assessmentPolicy"]
    store.set_binding(AssessmentBinding("runtime-a", current.character_id, 1, target.target_id,
        target.content_sha256, 1, policy["version"] + "+" + policy["weightProfile"]["profileId"]))
    hud = EquipmentAssessmentCoordinator(EquipmentAssessmentService(), store, lambda _: None).assess_commit_publish(
        runtime_instance_id="runtime-a", current=current, target=target, produced_at="2026-10-25T10:00:01Z")
    Draft202012Validator(load_json(CONTRACT / "schemas/hud.schema.json"), format_checker=FormatChecker()).validate(hud)


def test_present_value_does_not_prove_absence(tmp_path, validator):
    document = load_json(TARGET_FIXTURE)
    criterion = document["assessmentPolicy"]["criteria"][0]
    criterion["evidenceRequirement"] = "PRESENT_VALUE"
    document["assessmentPolicy"]["criteria"] = [criterion]
    target = ActivatedTarget(document["targetId"], document["displayName"], "a" * 64, 1, validator.validate(document))
    current = current_snapshot(attack=None, complete=False)
    result = EquipmentAssessmentService().assess(current, target)
    assert (result.score_status, result.evaluable_weight, result.fail_issues, result.warnings) == ("NO_DATA", 0, 0, 0)


@pytest.mark.parametrize("fault", ["empty", "unreadable", "oversized", "symlink"])
def test_active_restoration_independent_from_broken_neighbor(tmp_path, validator, monkeypatch, fault):
    folder = tmp_path / "targets"
    folder.mkdir()
    write_target(folder, "a.json")
    state = tmp_path / "selection.json"
    repo = TargetRepository(folder, state, validator, max_file_bytes=16384)
    listing = repo.list()
    entry = listing.entries[0]
    active = repo.activate(entry.target_id, entry.content_sha256, listing.revision)
    persisted = state.read_bytes()
    bad = folder / "b.json"
    bad.write_bytes(b"{}")
    if fault == "empty":
        bad.write_bytes(b"")
    elif fault == "oversized":
        bad.write_bytes(b"x" * 16385)
    elif fault == "symlink":
        bad.unlink()
        bad.symlink_to(folder / "a.json")
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if fault == "unreadable" and path == bad:
            raise PermissionError("synthetic read denied")
        return original_open(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guarded_open)
        for reader in (repo, TargetRepository(folder, state, validator, max_file_bytes=16384)):
            before_revision = reader._list_revision
            before_candidates = dict(reader._candidates)
            assert reader.get_active() == active
            assert reader._list_revision == before_revision
            assert reader._candidates == before_candidates
            with pytest.raises(TargetInvalid):
                reader.list()
            assert reader.get_active() == active
            assert reader._list_revision == before_revision
            assert state.read_bytes() == persisted
    bad.unlink()
    write_target(folder, "b.json", mutate=lambda doc: doc.update(targetId="target-b"))
    (folder / "malformed.json").write_bytes(b"{")
    restarted = TargetRepository(folder, state, validator, max_file_bytes=16384)
    assert restarted.get_active() == active
    recovered = restarted.list()
    assert sorted(e.validation for e in recovered.entries) == ["INVALID", "VALID", "VALID"]
    b = next(e for e in recovered.entries if e.target_id == "target-b")
    selected = restarted.activate(b.target_id, b.content_sha256, recovered.revision)
    assert selected.selection_revision == active.selection_revision + 1
    assert restarted.get_active() == selected


@pytest.mark.parametrize("fault", ["changed", "deleted", "invalid", "empty", "unreadable", "oversized", "symlink", "duplicate", "duplicate-changed"])
def test_active_restoration_revalidates_selected_target_without_fallback(tmp_path, validator, monkeypatch, fault):
    folder = tmp_path / "targets"
    folder.mkdir()
    a = write_target(folder, "a.json")
    write_target(folder, "other.json", mutate=lambda doc: doc.update(targetId="other-target"))
    state = tmp_path / "selection.json"
    repo = TargetRepository(folder, state, validator, max_file_bytes=16384)
    listing = repo.list()
    entry = next(e for e in listing.entries if e.target_id == "synthetic-charge-bolt")
    repo.activate(entry.target_id, entry.content_sha256, listing.revision)
    persisted = state.read_bytes()
    if fault == "changed":
        a.write_bytes(a.read_bytes() + b" ")
    elif fault == "deleted":
        a.unlink()
    elif fault == "invalid":
        a.write_bytes(b"{")
    elif fault == "empty":
        a.write_bytes(b"")
    elif fault == "oversized":
        a.write_bytes(b"x" * 16385)
    elif fault == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(a.read_bytes())
        a.unlink()
        a.symlink_to(outside)
    elif fault.startswith("duplicate"):
        write_target(folder, "duplicate.json", mutate=(
            (lambda doc: doc.update(displayName="Different bytes same ID"))
            if fault == "duplicate-changed" else None))
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if fault == "unreadable" and path == a:
            raise PermissionError("synthetic selected file read denied")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    for reader in (repo, TargetRepository(folder, state, validator, max_file_bytes=16384)):
        before_revision = reader._list_revision
        assert reader.get_active() is None
        assert reader._list_revision == before_revision
        assert state.read_bytes() == persisted
