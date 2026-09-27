"""Windows integrations for the node server."""

from .screen import WindowsScreenCaptureBackend
from .session import DesktopSessionInfo, desktop_session_info
from .steam import SteamProcess, WindowsSteamBackend

__all__ = [
    "DesktopSessionInfo",
    "SteamProcess",
    "WindowsScreenCaptureBackend",
    "WindowsSteamBackend",
    "desktop_session_info",
]
