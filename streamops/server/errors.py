"""Errors owned by the standalone StreamOps node server."""


class ServerError(Exception):
    """Base class for user-facing node server failures."""


class ServerConfigError(ServerError):
    """Raised when node server configuration is invalid."""


class RuntimeStateError(ServerError):
    """Raised when the node runtime cannot be started safely."""


class ScreenCaptureError(ServerError):
    """Raised when the Windows capture backend cannot produce an image."""


class WrongDesktopSessionError(ServerError):
    """Raised when an operation requires the active Windows desktop session."""

    def __init__(
        self,
        current_session_id: int,
        active_session_id: int,
        *,
        operation: str = "Screen capture",
    ) -> None:
        self.current_session_id = current_session_id
        self.active_session_id = active_session_id
        super().__init__(
            f"{operation} requires the active Windows console session "
            f"(current session {current_session_id}, active session {active_session_id})."
        )


class CaptureStorageError(ServerError):
    """Raised when a captured image cannot be persisted."""


class NoCaptureError(ServerError):
    """Raised when no successful screen capture exists yet."""


class SteamError(ServerError):
    """Base class for user-facing Steam management failures."""


class SteamNotFoundError(SteamError):
    """Raised when a usable Steam installation cannot be resolved."""


class SteamStatusError(SteamError):
    """Raised when Windows process state cannot be inspected safely."""


class SteamShutdownError(SteamError):
    """Raised when graceful Steam shutdown cannot be requested."""


class SteamShutdownTimeoutError(SteamError):
    """Raised when Steam does not exit within the graceful timeout."""


class SteamLaunchError(SteamError):
    """Raised when Steam cannot be launched and verified."""


class SteamRestartInProgressError(SteamError):
    """Raised when another Steam restart is already in progress."""


class InvalidSteamRestartRequestError(SteamError):
    """Raised when a restart request attempts to provide input."""


class ObsError(ServerError):
    """Base class for OBS control-plane failures."""


class ObsConnectionError(ObsError):
    """Raised when OBS WebSocket cannot be reached or authenticated."""


class ObsRequestError(ObsError):
    """Raised when OBS rejects a WebSocket request."""


class SceneOperationError(ObsError):
    """Raised when a scene apply/verify/review operation cannot complete."""


class SceneReviewNotFoundError(ObsError):
    """Raised when a requested in-memory review job does not exist."""


class SceneReviewInProgressError(ObsError):
    """Raised when an incompatible review operation is already running."""


class SceneProfileError(ServerError):
    """Base class for persisted scene-profile failures."""


class SceneProfileValidationError(SceneProfileError):
    """Raised when a scene profile does not conform to the supported schema."""


class SceneProfileNotFoundError(SceneProfileError):
    """Raised when a scene profile ID does not exist."""


class SceneProfileConflictError(SceneProfileError):
    """Raised when a profile write would overwrite a conflicting resource."""


class SceneProfileStorageError(SceneProfileError):
    """Raised when an atomic profile-store operation cannot complete."""
