"""Packaged Windows lifecycle support for the pinned OBS plugin."""

from .host import WindowsObsMultiRtmpHost
from .installer import InstallerResult, InstallerStatus, PluginInstallerFailure, WindowsObsMultiRtmpInstaller

__all__ = ["InstallerResult", "InstallerStatus", "PluginInstallerFailure", "WindowsObsMultiRtmpHost", "WindowsObsMultiRtmpInstaller"]
