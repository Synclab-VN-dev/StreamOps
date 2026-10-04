"""Windows integrations for the node server."""

from .screen import WindowsScreenCaptureBackend
from .session import DesktopSessionInfo, desktop_session_info
from .steam import SteamProcess, WindowsSteamBackend
from .obs_plugin import WindowsObsMultiRtmpHost

__all__ = [
    "DesktopSessionInfo",
    "SteamProcess",
    "WindowsScreenCaptureBackend",
    "WindowsObsMultiRtmpHost",
    "WindowsSteamBackend",
    "desktop_session_info",
]
