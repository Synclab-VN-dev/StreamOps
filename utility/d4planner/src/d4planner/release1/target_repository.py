from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


TARGET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class TargetError(RuntimeError):
    code = "TARGET_INVALID"


class TargetNotFound(TargetError):
    code = "TARGET_NOT_FOUND"


class TargetChanged(TargetError):
    code = "TARGET_CHANGED"


class TargetInvalid(TargetError):
    code = "TARGET_INVALID"


@dataclass(frozen=True, slots=True)
class TargetListEntry:
    target_id: str
    display_name: str
    content_sha256: str
    byte_length: int
    validation: str
    error_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActivatedTarget:
    target_id: str
    display_name: str
    content_sha256: str
    selection_revision: int
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TargetListing:
    revision: int
    entries: tuple[TargetListEntry, ...]


@dataclass(slots=True)
class _Candidate:
    path: Path
    entry: TargetListEntry
    document: dict[str, Any] | None


class TargetValidator:
    """Validate the versioned envelope and canonical build without modifying either."""

    def __init__(self, target_schema: dict[str, Any], canonical_schema: dict[str, Any]):
        canonical_id = canonical_schema.get("$id")
        if not canonical_id:
            raise ValueError("canonical schema requires $id")
        registry = Registry().with_resource(
            canonical_id, Resource.from_contents(canonical_schema)
        )
        self._validator = Draft202012Validator(
            target_schema, registry=registry, format_checker=FormatChecker()
        )

    @classmethod
    def from_contract_tree(cls, repository_root: Path) -> "TargetValidator":
        target_path = repository_root / "utility/d4planner/contracts/release1/v1/schemas/target.schema.json"
        canonical_path = repository_root / "utility/d4-rulekit/providers/maxroll/d4-build-v1.schema.json"
        return cls(
            json.loads(target_path.read_text(encoding="utf-8")),
            json.loads(canonical_path.read_text(encoding="utf-8")),
        )

    def validate(self, document: Any) -> dict[str, Any]:
        errors = sorted(self._validator.iter_errors(document), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.path) or "$"
            raise TargetInvalid(f"TARGET_SCHEMA_INVALID:{location}:{first.message}")
        assert isinstance(document, dict)
        criteria = document["assessmentPolicy"]["criteria"]
        criterion_ids: set[str] = set()
        criterion_orders: set[int] = set()
        criterion_bindings: set[tuple[str, str, str, str, int]] = set()
        slots = {
            slot["slotId"]: slot["item"]
            for slot in document["canonicalBuild"]["equipment"]["slots"]
        }
        group_keys = {
            "AFFIXES": "affixes", "IMPLICITS": "implicits",
            "ASPECTS": "aspects", "TEMPERS": "tempers",
        }
        for criterion in criteria:
            criterion_id = criterion["criterionId"]
            if criterion_id in criterion_ids:
                raise TargetInvalid(f"DUPLICATE_CRITERION:{criterion_id}")
            criterion_ids.add(criterion_id)
            target_order = criterion["targetOrder"]
            if target_order in criterion_orders:
                raise TargetInvalid(f"DUPLICATE_TARGET_ORDER:{target_order}")
            criterion_orders.add(target_order)
            binding = (
                criterion["slotId"], criterion["kind"], criterion["entityId"],
                criterion["source"]["group"], criterion["source"]["occurrence"],
            )
            if binding in criterion_bindings:
                raise TargetInvalid(f"DUPLICATE_CRITERION_BINDING:{criterion_id}")
            criterion_bindings.add(binding)
            if criterion["core"] != (criterion["weightClass"] == "CORE"):
                raise TargetInvalid(f"WEIGHT_CLASS_MISMATCH:{criterion_id}")
            item = slots.get(criterion["slotId"])
            if item is None:
                raise TargetInvalid(f"CRITERION_SLOT_MISSING:{criterion_id}")
            entities = item[group_keys[criterion["source"]["group"]]]
            matching = [e for e in entities if e["entityId"] == criterion["entityId"]]
            occurrence = criterion["source"]["occurrence"]
            if occurrence >= len(matching):
                raise TargetInvalid(f"CRITERION_ENTITY_MISSING:{criterion_id}")
            values = matching[occurrence].get("values", [])
            parameter_ids: set[str] = set()
            parameter_indices: set[int] = set()
            for parameter in criterion["parameters"]:
                parameter_id = parameter["parameterId"]
                if parameter_id in parameter_ids:
                    raise TargetInvalid(f"DUPLICATE_PARAMETER:{criterion_id}:{parameter_id}")
                parameter_ids.add(parameter_id)
                if parameter["index"] in parameter_indices:
                    raise TargetInvalid(f"DUPLICATE_PARAMETER_INDEX:{criterion_id}:{parameter['index']}")
                parameter_indices.add(parameter["index"])
                if parameter["comparator"] != "PRESENT" and parameter["index"] >= len(values):
                    raise TargetInvalid(f"PARAMETER_INDEX_MISSING:{criterion_id}:{parameter_id}")
        return document


class TargetRepository:
    """Safe, request-driven target listing and hash-bound atomic activation."""

    def __init__(
        self,
        configured_root: Path,
        selection_state: Path,
        validator: TargetValidator,
        *,
        max_file_bytes: int = 2 * 1024 * 1024,
        max_files: int = 256,
    ):
        self.configured_root = configured_root.resolve()
        self.selection_state = selection_state
        self.validator = validator
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.configured_root.mkdir(parents=True, exist_ok=True)
        self.selection_state.parent.mkdir(parents=True, exist_ok=True)
        self._list_revision = 0
        self._candidates: dict[str, _Candidate] = {}

    @staticmethod
    def _invalid_id(path: Path, data: bytes) -> str:
        return "invalid-" + sha256(path.name.encode("utf-8") + data).hexdigest()[:16]

    def _read_candidate(self, path: Path) -> _Candidate:
        if path.is_symlink() or path.resolve().parent != self.configured_root:
            raise TargetInvalid("UNSAFE_TARGET_PATH")
        size = path.stat().st_size
        if size <= 0 or size > self.max_file_bytes:
            raise TargetInvalid("TARGET_SIZE_INVALID")
        # Bound the read and validate actual bytes too: size may change after stat.
        with path.open("rb") as stream:
            data = stream.read(self.max_file_bytes + 1)
        if not data or len(data) > self.max_file_bytes:
            raise TargetInvalid("TARGET_SIZE_INVALID")
        digest = sha256(data).hexdigest()
        try:
            parsed = json.loads(data.decode("utf-8"))
            document = self.validator.validate(parsed)
            target_id = document["targetId"]
            display_name = document["displayName"]
            return _Candidate(
                path,
                TargetListEntry(target_id, display_name, digest, len(data), "VALID", ()),
                document,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TargetInvalid) as exc:
            code = str(exc).split(":", 1)[0] or "TARGET_INVALID"
            return _Candidate(
                path,
                TargetListEntry(
                    self._invalid_id(path, data), path.name, digest, len(data),
                    "INVALID", (code,),
                ),
                None,
            )

    def _refresh_candidates(self) -> tuple[TargetListEntry, ...]:
        """Refresh filesystem state without changing the FE list generation."""
        candidates: list[_Candidate] = []
        paths = [
            path for path in sorted(self.configured_root.iterdir(), key=lambda p: p.name.casefold())
            if path.suffix.lower() == ".json" and path.is_file()
        ]
        if len(paths) > self.max_files:
            raise TargetInvalid("TARGET_FILE_LIMIT_EXCEEDED")
        for path in paths:
            try:
                candidates.append(self._read_candidate(path))
            except OSError:
                # No content evidence exists. Fail the operation through the
                # existing TARGET_INVALID error, never fabricate a descriptor.
                raise TargetInvalid("TARGET_READ_FAILED") from None
        by_id: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            by_id.setdefault(candidate.entry.target_id, []).append(candidate)
        for duplicate_id, duplicate_candidates in by_id.items():
            if len(duplicate_candidates) < 2:
                continue
            for candidate in duplicate_candidates:
                candidate.entry = TargetListEntry(
                    candidate.entry.target_id, candidate.entry.display_name,
                    candidate.entry.content_sha256, candidate.entry.byte_length,
                    "INVALID", ("DUPLICATE_TARGET_ID",),
                )
                candidate.document = None
        self._candidates = {candidate.entry.target_id: candidate for candidate in candidates}
        return tuple(candidate.entry for candidate in candidates)

    def list(self) -> TargetListing:
        entries = self._refresh_candidates()
        self._list_revision += 1
        return TargetListing(self._list_revision, entries)

    def _load_selection(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.selection_state.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None

    def _persist_selection(self, value: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=".target-selection-", suffix=".tmp", dir=self.selection_state.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, separators=(",", ":"), sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.selection_state)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def activate(
        self,
        target_id: str,
        expected_sha256: str,
        expected_list_revision: int,
    ) -> ActivatedTarget:
        if not TARGET_ID.fullmatch(target_id):
            raise TargetNotFound("TARGET_NOT_FOUND")
        if expected_list_revision != self._list_revision:
            raise TargetChanged("TARGET_LIST_CHANGED")
        candidate = self._candidates.get(target_id)
        if candidate is None:
            raise TargetNotFound("TARGET_NOT_FOUND")
        if candidate.entry.validation != "VALID":
            raise TargetInvalid("TARGET_INVALID")
        try:
            refreshed = self._read_candidate(candidate.path)
        except (FileNotFoundError, OSError):
            raise TargetNotFound("TARGET_NOT_FOUND") from None
        if refreshed.entry.validation != "VALID":
            raise TargetInvalid("TARGET_INVALID")
        if refreshed.entry.content_sha256 != expected_sha256:
            raise TargetChanged("TARGET_CHANGED")
        previous = self._load_selection()
        revision = int(previous.get("selectionRevision", 0)) + 1 if previous else 1
        state = {
            "targetId": target_id,
            "contentSha256": expected_sha256,
            "selectionRevision": revision,
            "policyVersion": (
                refreshed.document["assessmentPolicy"]["version"] + "+" +
                refreshed.document["assessmentPolicy"]["weightProfile"]["profileId"]
            ),
        }
        self._persist_selection(state)
        assert refreshed.document is not None
        return ActivatedTarget(
            target_id, refreshed.entry.display_name, expected_sha256,
            revision, refreshed.document,
        )

    def get_active(self) -> ActivatedTarget | None:
        state = self._load_selection()
        if not state:
            return None
        # Active-state revalidation is an internal read. It must not invalidate
        # a Target list revision already handed to FE.
        self._refresh_candidates()
        candidate = self._candidates.get(str(state.get("targetId", "")))
        if candidate is None or candidate.entry.validation != "VALID":
            return None
        if candidate.entry.content_sha256 != state.get("contentSha256"):
            return None
        assert candidate.document is not None
        return ActivatedTarget(
            candidate.entry.target_id, candidate.entry.display_name,
            candidate.entry.content_sha256, int(state["selectionRevision"]),
            candidate.document,
        )
