from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from d4planner.managed_backend import CONTRACT, PROTOCOL, BootstrapError, load_bootstrap


def descriptor(tmp_path: Path) -> tuple[Path, dict]:
    data = {
        "protocol": PROTOCOL,
        "contractVersion": CONTRACT,
        "ownerInstanceId": "owner-test-a",
        "childInstanceId": "child-test-a",
        "generation": 1,
        "dataDir": str(tmp_path / "data"),
        "targetFolder": str(tmp_path / "targets"),
        "wsEndpoint": {"host": "127.0.0.1", "port": 0},
        "credential": "a" * 32,
    }
    path = tmp_path / "bootstrap.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path, data


def test_bootstrap_rejects_non_loopback_and_secret_is_not_echoed(tmp_path: Path) -> None:
    path, data = descriptor(tmp_path)
    data["wsEndpoint"]["host"] = "0.0.0.0"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BootstrapError, match="loopback"):
        load_bootstrap(path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not Windows ACL evidence")
def test_bootstrap_requires_owner_only_permissions(tmp_path: Path) -> None:
    path, _ = descriptor(tmp_path)
    path.chmod(0o644)
    with pytest.raises(BootstrapError, match="owner-only"):
        load_bootstrap(path)


def test_real_managed_process_ready_empty_folder_and_owned_shutdown(tmp_path: Path) -> None:
    path, expected = descriptor(tmp_path)
    env = os.environ.copy()
    env["D4PLANNER_BOOTSTRAP_FILE"] = str(path)
    process = subprocess.Popen(
        [sys.executable, "-m", "d4planner.managed_backend"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdout and process.stdin and process.stderr
    ready = json.loads(process.stdout.readline())
    assert ready["event"] == "READY"
    assert ready["pid"] == process.pid
    assert ready["health"] == {
        "durableState": "READY", "targetRepository": "READY", "targetJsonCount": 0,
        "wsTransport": "PENDING_S5", "ruleKitWorker": "PENDING_S3",
    }
    assert expected["credential"] not in json.dumps(ready)
    process.stdin.write(json.dumps({
        "type": "shutdown", "ownerInstanceId": expected["ownerInstanceId"],
        "childInstanceId": expected["childInstanceId"], "generation": expected["generation"],
    }) + "\n")
    process.stdin.flush()
    exit_event = json.loads(process.stdout.readline())
    assert exit_event["event"] == "EXIT"
    assert exit_event["reason"] == "OWNER_STOP"
    assert process.wait(timeout=3) == 0
    assert expected["credential"] not in process.stderr.read()


def test_invalid_target_file_is_domain_state_not_startup_failure(tmp_path: Path) -> None:
    path, expected = descriptor(tmp_path)
    target_folder = Path(expected["targetFolder"])
    target_folder.mkdir()
    (target_folder / "invalid.json").write_text("{not-json", encoding="utf-8")
    env = os.environ.copy()
    env["D4PLANNER_BOOTSTRAP_FILE"] = str(path)
    process = subprocess.Popen(
        [sys.executable, "-m", "d4planner.managed_backend"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    assert process.stdout and process.stdin
    ready = json.loads(process.stdout.readline())
    assert ready["event"] == "READY"
    assert ready["health"]["targetRepository"] == "READY"
    assert ready["health"]["targetJsonCount"] == 1
    process.stdin.close()
    assert json.loads(process.stdout.readline())["reason"] == "PARENT_EOF"
    assert process.wait(timeout=3) == 0


def test_parent_pipe_eof_stops_child_without_detaching(tmp_path: Path) -> None:
    path, _ = descriptor(tmp_path)
    env = os.environ.copy()
    env["D4PLANNER_BOOTSTRAP_FILE"] = str(path)
    process = subprocess.Popen(
        [sys.executable, "-m", "d4planner.managed_backend"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    assert process.stdout and process.stdin
    assert json.loads(process.stdout.readline())["event"] == "READY"
    process.stdin.close()
    assert json.loads(process.stdout.readline())["reason"] == "PARENT_EOF"
    assert process.wait(timeout=3) == 0


def test_wrong_owner_cannot_stop_owned_process(tmp_path: Path) -> None:
    path, expected = descriptor(tmp_path)
    env = os.environ.copy()
    env["D4PLANNER_BOOTSTRAP_FILE"] = str(path)
    process = subprocess.Popen(
        [sys.executable, "-m", "d4planner.managed_backend"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    assert process.stdout and process.stdin
    assert json.loads(process.stdout.readline())["event"] == "READY"
    process.stdin.write(json.dumps({
        "type": "shutdown", "ownerInstanceId": "some-other-owner",
        "childInstanceId": expected["childInstanceId"], "generation": expected["generation"],
    }) + "\n")
    process.stdin.flush()
    assert json.loads(process.stdout.readline()) == {
        "event": "ERROR", "code": "OWNERSHIP_MISMATCH",
    }
    assert process.poll() is None
    process.stdin.write(json.dumps({
        "type": "shutdown", "ownerInstanceId": expected["ownerInstanceId"],
        "childInstanceId": expected["childInstanceId"], "generation": expected["generation"],
    }) + "\n")
    process.stdin.flush()
    assert json.loads(process.stdout.readline())["reason"] == "OWNER_STOP"
    assert process.wait(timeout=3) == 0
