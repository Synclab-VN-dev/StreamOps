"""Application service for producing and retaining the latest screen capture."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
import os
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from PIL import Image

from ..errors import CaptureStorageError, NoCaptureError, ScreenCaptureError, WrongDesktopSessionError


class CaptureBackend(Protocol):
    def start(self) -> None: ...

    def capture(self, timeout: float) -> Any: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class CaptureMetadata:
    capture_id: str
    captured_at: str
    width: int
    height: int
    content_type: str = "image/png"

    def api_payload(self) -> dict[str, object]:
        return {**asdict(self), "latest_url": f"/api/v1/screen/latest?v={self.capture_id}"}


@dataclass(frozen=True)
class LatestCapture:
    metadata: CaptureMetadata
    content: bytes


class ScreenCaptureService:
    def __init__(self, backend: CaptureBackend, data_dir: Path, timeout: float) -> None:
        self.backend = backend
        self.data_dir = data_dir
        self.timeout = timeout
        self.latest_path = data_dir / "latest.png"
        self._capture_lock = asyncio.Lock()
        self._latest: LatestCapture | None = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def backend_name(self) -> str | None:
        value = getattr(self.backend, "backend_name", None)
        return value if isinstance(value, str) else None

    def start(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            probe = self.data_dir / f".write-probe-{uuid4().hex}"
            probe.write_bytes(b"")
            probe.unlink()
            if self.latest_path.exists():
                self._latest = self._load_existing_capture()
        except OSError as exc:
            raise CaptureStorageError(f"Data directory is not writable: {self.data_dir}") from exc
        try:
            self.backend.start()
        except (ScreenCaptureError, WrongDesktopSessionError):
            self._ready = False
        else:
            # Initialization alone is insufficient: some desktop APIs create a
            # capture object but cannot deliver a frame in the current session.
            self._ready = False

    def close(self) -> None:
        self.backend.close()
        self._ready = False

    async def capture(self) -> CaptureMetadata:
        async with self._capture_lock:
            return await asyncio.to_thread(self._capture_sync)

    def latest(self) -> LatestCapture:
        if self._latest is None:
            raise NoCaptureError("No successful screen capture exists yet.")
        return self._latest

    def _capture_sync(self) -> CaptureMetadata:
        try:
            frame = self.backend.capture(self.timeout)
        except (ScreenCaptureError, WrongDesktopSessionError):
            self._ready = False
            raise
        self._ready = True
        try:
            image = frame if isinstance(frame, Image.Image) else Image.fromarray(frame)
            width, height = image.size
            if image.mode != "RGB":
                image = image.convert("RGB")
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            content = buffer.getvalue()
        except Exception as exc:
            raise ScreenCaptureError(f"Could not encode the captured frame: {exc}") from exc

        captured_at = datetime.now(UTC)
        capture_id = f"{captured_at.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}"
        metadata = CaptureMetadata(
            capture_id=capture_id,
            captured_at=captured_at.isoformat().replace("+00:00", "Z"),
            width=width,
            height=height,
        )
        temporary_path = self.data_dir / f"latest.{uuid4().hex}.tmp"
        try:
            with temporary_path.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.latest_path)
        except OSError as exc:
            raise CaptureStorageError(f"Could not persist latest capture: {exc}") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

        self._latest = LatestCapture(metadata=metadata, content=content)
        return metadata

    def _load_existing_capture(self) -> LatestCapture:
        content = self.latest_path.read_bytes()
        try:
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                image.verify()
        except Exception as exc:
            raise CaptureStorageError(f"Existing latest capture is invalid: {self.latest_path}") from exc
        stat = self.latest_path.stat()
        captured_at = datetime.fromtimestamp(stat.st_mtime, UTC)
        metadata = CaptureMetadata(
            capture_id=f"persisted-{stat.st_mtime_ns}",
            captured_at=captured_at.isoformat().replace("+00:00", "Z"),
            width=width,
            height=height,
        )
        return LatestCapture(metadata=metadata, content=content)
