from __future__ import annotations

import json
from pathlib import Path

from streamops.errors import ObsConnectionError
from streamops.obs.client import ObsClient


def test_from_env_reads_local_obs_websocket_config(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "obs-studio" / "plugin_config" / "obs-websocket"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "auth_required": True,
                "server_password": "local-password",
                "server_port": 4466,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("OBS_WEBSOCKET_PASSWORD", raising=False)
    monkeypatch.delenv("OBS_WEBSOCKET_PORT", raising=False)

    client = ObsClient.from_env()

    assert client.password == "local-password"
    assert client.port == 4466


def test_from_env_prefers_explicit_env_over_local_config(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "obs-studio" / "plugin_config" / "obs-websocket"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "auth_required": True,
                "server_password": "local-password",
                "server_port": 4466,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("OBS_WEBSOCKET_PASSWORD", "env-password")
    monkeypatch.setenv("OBS_WEBSOCKET_PORT", "4457")

    client = ObsClient.from_env()

    assert client.password == "env-password"
    assert client.port == 4457


def test_from_env_ignores_local_password_when_auth_is_disabled(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "obs-studio" / "plugin_config" / "obs-websocket"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "auth_required": False,
                "server_password": "local-password",
                "server_port": 4455,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("OBS_WEBSOCKET_PASSWORD", raising=False)

    client = ObsClient.from_env()

    assert client.password is None

def test_legacy_from_env_preserves_obs_connection_error(monkeypatch) -> None:
    monkeypatch.setenv("OBS_WEBSOCKET_PORT", "not-a-port")

    try:
        ObsClient.from_env()
    except Exception as exc:
        assert isinstance(exc, ObsConnectionError)
    else:
        raise AssertionError("Expected invalid OBS_WEBSOCKET_PORT to fail.")

