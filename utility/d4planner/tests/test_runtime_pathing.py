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
