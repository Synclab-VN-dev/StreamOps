import os
from pathlib import Path

from d4planner.runtime.pathing import MemoryPathBackend, UserPathManager
from d4planner.runtime.store import RuntimePaths, read_json


def test_user_path_ensure_is_idempotent_and_never_touches_machine_path(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    backend = MemoryPathBackend(
        user_path=os.pathsep.join(["A", "B"]),
        machine_path=os.pathsep.join(["M1", "M2"]),
    )
    manager = UserPathManager(paths, backend)
    managed = paths.controller

    first = manager.ensure(managed)
    second = manager.ensure(managed)

    assert first.changed is True
    assert second.changed is False
    parts = backend.user_path.split(os.pathsep)
    assert parts.count(str(managed.resolve())) == 1
    assert backend.machine_path == os.pathsep.join(["M1", "M2"])


def test_restore_returns_original_path_when_unchanged_by_others(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    original = os.pathsep.join(["A", "B"])
    backend = MemoryPathBackend(user_path=original, machine_path="M")
    manager = UserPathManager(paths, backend)

    manager.ensure(paths.controller)
    restored = manager.restore()

    assert restored.changed is True
    assert backend.user_path == original


def test_restore_preserves_unrelated_user_edits(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    backend = MemoryPathBackend(user_path="A", machine_path="M")
    manager = UserPathManager(paths, backend)

    manager.ensure(paths.controller)
    backend.user_path = backend.user_path + os.pathsep + "USER_NEW"
    manager.restore()

    assert "USER_NEW" in backend.user_path.split(os.pathsep)
    assert str(paths.controller.resolve()) not in backend.user_path.split(os.pathsep)


def test_preexisting_managed_path_is_never_removed_on_restore(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    managed = str(paths.controller.resolve())
    backend = MemoryPathBackend(user_path=os.pathsep.join(["A", managed, "B"]), machine_path="M")
    manager = UserPathManager(paths, backend)

    change = manager.ensure(paths.controller)
    assert change.changed is False

    restored = manager.restore()
    assert restored.changed is False
    assert managed in backend.user_path.split(os.pathsep)


def test_lost_metadata_does_not_invent_a_path_change(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    backend = MemoryPathBackend(user_path=str(paths.controller.resolve()))
    manager = UserPathManager(paths, backend)
    first = manager.ensure(paths.controller)
    second = manager.ensure(paths.controller)
    assert not first.changed and not second.changed
    assert first.updated_at is None and second.updated_at is None
    assert manager.managed_updated_at() is None


def test_old_preexisting_observation_is_not_a_path_change(tmp_path):
    from d4planner.runtime.store import atomic_write_json
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    atomic_write_json(paths.path_managed, {
        "managedPath": str(paths.controller.resolve()), "owned": False,
        "preExisting": True, "updatedAt": "2026-11-10T12:29:27+07:00",
    })
    manager = UserPathManager(paths, MemoryPathBackend(user_path=str(paths.controller.resolve())))
    assert manager.ensure(paths.controller).updated_at is None
    assert manager.managed_updated_at() is None


def test_real_path_change_retains_timestamp_across_ensure(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    manager = UserPathManager(paths, MemoryPathBackend(user_path="OTHER"))
    first = manager.ensure(paths.controller)
    assert first.changed and first.updated_at
    assert manager.ensure(paths.controller).updated_at == first.updated_at
    assert manager.managed_updated_at() == first.updated_at
