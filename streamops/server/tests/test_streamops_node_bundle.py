from pathlib import Path

import pytest

from scripts.release.streamops_node_bundle import pack, verify


COMMIT = "a" * 40


def test_deployment_bundle_round_trip_and_tamper_detection(tmp_path: Path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    app = wheelhouse / "streamops-0.1.0-py3-none-any.whl"
    dependency = wheelhouse / "fastapi-1.0.0-py3-none-any.whl"
    app.write_bytes(b"app-wheel")
    dependency.write_bytes(b"dependency-wheel")
    pack(tmp_path, COMMIT)
    verify(tmp_path, COMMIT)
    app.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="differs"):
        verify(tmp_path, COMMIT)


def test_deployment_bundle_requires_one_streamops_wheel(tmp_path: Path):
    (tmp_path / "wheelhouse").mkdir()
    with pytest.raises(ValueError, match="exactly one"):
        pack(tmp_path, COMMIT)
