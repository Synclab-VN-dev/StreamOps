"""Backend isolation, first-usable short circuit, and CLI diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from .model import BackendResult, ProbeStatus


class ProbeBackend(Protocol):
    name: str

    def probe(self, seconds: float) -> BackendResult: ...


def run_backends(seconds: float, backends: Sequence[ProbeBackend]) -> list[BackendResult]:
    if seconds <= 0:
        raise ValueError("--seconds must be greater than zero")
    results: list[BackendResult] = []
    for backend in backends:
        try:
            result = backend.probe(seconds)
            if result.backend != backend.name:
                raise ValueError("backend identity mismatch")
        except Exception as exc:
            result = BackendResult(
                backend=backend.name,
                status=ProbeStatus.ERROR,
                detail=f"{type(exc).__name__}: {exc}",
            )
        results.append(result)
        if result.usable:
            break
    return results


def render(results: Sequence[BackendResult]) -> str:
    lines: list[str] = []
    for result in results:
        lines.extend((
            f"Backend {result.backend}:",
            f"  runtime: {result.runtime}",
            f"  controller: {'YES' if result.devices else 'NO'}",
            f"  status: {result.status.value}",
            f"  devices: {len(result.devices)}",
            f"  button events: {len(result.events)}",
        ))
        if result.detail:
            lines.append(f"  detail: {result.detail}")
        for device in result.devices:
            lines.append("  device: " + " ".join(
                f"{key}={value}" for key, value in sorted(device.items())
            ))
        for event in result.events:
            lines.append(
                f"[{event.backend}] device={event.device_id} "
                f"control={event.raw_control_id} {event.state} at={event.timestamp}"
            )
    return "\n".join(lines)


def collect(seconds: float, backend_factories: Sequence[Callable[[], ProbeBackend]]) -> list[BackendResult]:
    """Instantiate each backend independently, preserving failure isolation."""
    if seconds <= 0:
        raise ValueError("--seconds must be greater than zero")

    class LazyBackend:
        def __init__(self, name: str, factory: Callable[[], ProbeBackend]):
            self.name = name
            self.factory = factory

        def probe(self, duration: float) -> BackendResult:
            return self.factory().probe(duration)

    # Factory functions should set an explicit stable name for reporting.
    backends = [LazyBackend(getattr(f, "backend_name", f.__name__), f) for f in backend_factories]
    return run_backends(seconds, backends)
