"""Interactive-session Tolk health probe invoked by the scheduled-task bridge."""

from __future__ import annotations

import argparse
from pathlib import Path

from .store import RuntimePaths, atomic_write_json, read_json
from .windows import WindowsRuntime


def run(root: Path) -> int:
    paths = RuntimePaths(root)
    request = read_json(paths.state / "tolk-probe-request.json") or {}
    runtime = WindowsRuntime(paths)
    health = runtime._probe_tolk_local()
    atomic_write_json(
        paths.state / "tolk-probe-result.json",
        {
            "requestId": request.get("requestId"),
            "sessionId": runtime.current_process_session_id(),
            **health.as_dict(),
        },
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    return run(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
