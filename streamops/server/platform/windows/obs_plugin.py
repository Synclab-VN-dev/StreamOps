"""Fixed-command PowerShell adapter for the obs-multi-rtmp host installer."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ...errors import ObsPluginError
from ...services.obs_plugin import PluginHostResult, PluginHostStatus


class WindowsObsMultiRtmpHost:
    def __init__(
        self,
        *,
        script: Path | None = None,
        executable: str | None = None,
        timeout: float = 180.0,
        runner: Any = subprocess.run,
    ) -> None:
        repository = Path(__file__).resolve().parents[4]
        self.script = script or repository / "scripts" / "devices" / "a-windows" / "manage-obs-multi-rtmp.ps1"
        self.executable = executable
        self.timeout = timeout
        self.runner = runner

    def status(self) -> PluginHostStatus:
        return self._status_from(self._invoke("Status"))

    def install(self) -> PluginHostResult:
        payload = self._invoke("Install")
        return PluginHostResult(str(payload["result"]))

    def verify(self) -> PluginHostStatus:
        return self._status_from(self._invoke("Verify"))

    def rollback(self) -> PluginHostResult:
        payload = self._invoke("Rollback")
        return PluginHostResult(str(payload["result"]))

    def _status_from(self, payload: dict[str, Any]) -> PluginHostStatus:
        installation = payload.get("installation")
        if installation not in {"absent", "exact", "conflict"}:
            raise ObsPluginError("plugin_status_failed", "Plugin host returned an invalid status.", 503)
        return PluginHostStatus(
            installation=installation,
            compatible=payload.get("compatible") is True,
            loaded=payload.get("loaded") is True,
            loaded_version=(str(payload["loaded_version"]) if payload.get("loaded_version") else None),
        )

    def _invoke(self, action: str) -> dict[str, Any]:
        executable = self.executable or shutil.which("pwsh.exe") or shutil.which("pwsh")
        if not executable or not self.script.is_file():
            raise ObsPluginError("plugin_status_failed", "The fixed OBS plugin host installer is unavailable.", 503)
        command = [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.script),
            "-Action",
            action,
            "-Confirm:$false",
        ]
        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8-sig",
                errors="replace",
                timeout=self.timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ObsPluginError(self._failure_code(action), "The plugin host operation timed out.", 503) from exc
        except PermissionError:
            raise
        except OSError as exc:
            raise ObsPluginError(self._failure_code(action), "The plugin host operation could not start.", 503) from exc

        payload = self._parse_json(completed.stdout)
        if completed.returncode != 0 or payload.get("ok") is False:
            self._raise_host_error(action, payload)
        return payload

    @staticmethod
    def _parse_json(stdout: str) -> dict[str, Any]:
        try:
            payload = json.loads(stdout.strip())
        except (json.JSONDecodeError, AttributeError) as exc:
            raise ObsPluginError("plugin_status_failed", "Plugin host returned invalid output.", 503) from exc
        if not isinstance(payload, dict):
            raise ObsPluginError("plugin_status_failed", "Plugin host returned invalid output.", 503)
        return payload

    def _raise_host_error(self, action: str, payload: dict[str, Any]) -> None:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        lower_code = error.get("code")
        if lower_code == "permission_denied":
            raise PermissionError("OBS plugin directory permission denied")
        if lower_code == "incompatible_obs":
            raise ObsPluginError("plugin_incompatible", "The pinned plugin is incompatible with this OBS version.", 409)
        if lower_code in {"obs_not_running", "module_not_loaded", "version_not_loaded", "manifest_mismatch"} and action == "Verify":
            raise ObsPluginError("plugin_verify_failed", "The pinned plugin is not loaded by the current OBS process.", 409)
        if lower_code in {"transaction_missing", "rollback_conflict", "config_conflict"}:
            raise ObsPluginError("plugin_state_conflict", "The plugin state cannot be changed safely.", 409)
        raise ObsPluginError(self._failure_code(action), "The plugin host operation failed.", 503)

    @staticmethod
    def _failure_code(action: str) -> str:
        return {
            "Install": "plugin_install_failed",
            "Verify": "plugin_verify_failed",
            "Rollback": "plugin_rollback_failed",
        }.get(action, "plugin_status_failed")
