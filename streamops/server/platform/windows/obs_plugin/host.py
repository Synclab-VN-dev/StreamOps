"""Service-facing adapter for the packaged Windows plugin installer."""

from __future__ import annotations

from pathlib import Path

from ....errors import ObsPluginError
from ....services.obs_plugin_release_source import configured_plugin_release_source
from .installer import InstallerResult, InstallerStatus, PluginInstallerFailure, WindowsObsMultiRtmpInstaller


class WindowsObsMultiRtmpHost:
    def __init__(self, data_dir: Path, *, obs_executable: Path | None = None) -> None:
        self.release_source = configured_plugin_release_source()
        kwargs = {"release_source": self.release_source}
        if obs_executable is not None:
            kwargs["obs_executable"] = Path(obs_executable)
        self.installer = WindowsObsMultiRtmpInstaller(data_dir, **kwargs)

    def status(self) -> InstallerStatus:
        try:
            return self.installer.status()
        except PermissionError as exc:
            raise ObsPluginError("plugin_status_failed", "OBS plugin status could not be inspected.", 503) from exc
        except Exception as exc:
            raise ObsPluginError("plugin_status_failed", "OBS plugin status could not be inspected.", 503) from exc

    def install(self) -> InstallerResult:
        return self._invoke("install")

    def adopt(self) -> InstallerResult:
        return self._invoke("adopt")

    def update(self) -> InstallerResult:
        return self._invoke("update")

    def verify(self) -> InstallerStatus:
        return self._invoke("verify")

    def rollback(self) -> InstallerResult:
        return self._invoke("rollback")

    def _invoke(self, action: str):
        try:
            result = getattr(self.installer, action)()
        except PermissionError as exc:
            raise ObsPluginError("plugin_install_permission_denied", "StreamOps cannot modify the managed plugin directory.", 403) from exc
        except PluginInstallerFailure as exc:
            if action == "adopt" and exc.code == "obs_running":
                code, status = "plugin_adopt_requires_obs_stopped", 409
            else:
                code, status = _ERRORS.get(exc.code, (f"plugin_{action}_failed", 503))
            raise ObsPluginError(code, _PUBLIC_MESSAGES.get(code, "OBS plugin operation failed."), status) from exc
        except OSError as exc:
            if getattr(exc, "winerror", None) == 5 or getattr(exc, "errno", None) in {1, 13}:
                raise ObsPluginError("plugin_install_permission_denied", "StreamOps cannot modify the managed plugin directory.", 403) from exc
            raise ObsPluginError(f"plugin_{action}_failed", "OBS plugin operation failed.", 503) from exc
        return result


_ERRORS = {
    "incompatible_obs": ("plugin_incompatible", 409),
    "manifest_mismatch": ("plugin_verify_failed", 409),
    "obs_not_running": ("plugin_verify_failed", 409),
    "module_not_loaded": ("plugin_verify_failed", 409),
    "version_not_loaded": ("plugin_verify_failed", 409),
    "rollback_conflict": ("plugin_state_conflict", 409),
    "config_conflict": ("plugin_state_conflict", 409),
    "transaction_missing": ("plugin_state_conflict", 409),
    "obs_running": ("plugin_state_conflict", 409),
    "adoption_required": ("plugin_adoption_required", 409),
    "backup_invalid": ("plugin_backup_invalid", 409),
    "recovery_required": ("plugin_recovery_required", 409),
    "permission_denied": ("plugin_install_permission_denied", 403),
    "plugin_state_conflict": ("plugin_state_conflict", 409),
    "download_failed": ("plugin_install_failed", 503),
    "artifact_hash_mismatch": ("plugin_install_failed", 503),
    "artifact_invalid": ("plugin_install_failed", 503),
    "artifact_manifest_mismatch": ("plugin_install_failed", 503),
    "install_failed": ("plugin_install_failed", 503),
    "update_failed": ("plugin_update_failed", 503),
    "update_not_available": ("plugin_state_conflict", 409),
    "release_unavailable": ("plugin_release_unavailable", 503),
}

_PUBLIC_MESSAGES = {
    "plugin_incompatible": "The pinned plugin is incompatible with this OBS version.",
    "plugin_state_conflict": "The plugin state cannot be changed safely.",
    "plugin_install_permission_denied": "StreamOps does not have permission to modify the OBS plugin directory.",
    "plugin_install_failed": "OBS plugin installation failed.",
    "plugin_adopt_failed": "Existing OBS plugin adoption failed.",
    "plugin_adoption_required": "Existing plugin files must be explicitly adopted first.",
    "plugin_adopt_requires_obs_stopped": "OBS must be stopped before adopting existing plugin files.",
    "plugin_backup_invalid": "The plugin backup could not be verified.",
    "plugin_recovery_required": "An unfinished plugin transaction requires explicit recovery.",
    "plugin_update_failed": "OBS plugin update failed.",
    "plugin_release_unavailable": "No approved managed plugin release is available.",
    "plugin_verify_failed": "The pinned plugin load could not be verified.",
    "plugin_rollback_failed": "OBS plugin rollback failed.",
}
