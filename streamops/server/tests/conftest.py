from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image
import pytest

from streamops.server.config import ServerConfig
from streamops.server.services import ScreenCaptureService


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Run sync Playwright last because its session fixture owns an asyncio loop."""
    regular = [item for item in items if "e2e" not in item.path.parts]
    browser = [item for item in items if "e2e" in item.path.parts]
    items[:] = [*regular, *browser]


class FakeCaptureBackend:
    def __init__(self, frames: list[Any] | None = None) -> None:
        self.frames = deque(frames or [Image.new("RGB", (8, 6), "#2da486")])
        self.started = False
        self.closed = False
        self.backend_name = "fake"

    def start(self) -> None:
        self.started = True

    def capture(self, timeout: float) -> Any:
        value = self.frames.popleft() if len(self.frames) > 1 else self.frames[0]
        if isinstance(value, Exception):
            raise value
        return value.copy() if isinstance(value, Image.Image) else value

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def server_config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        host="127.0.0.1",
        port=8765,
        output_index=0,
        data_dir=tmp_path,
        capture_timeout=0.5,
        log_level="info",
    )


@pytest.fixture
def capture_service(server_config: ServerConfig) -> ScreenCaptureService:
    return ScreenCaptureService(FakeCaptureBackend(), server_config.data_dir, server_config.capture_timeout)
