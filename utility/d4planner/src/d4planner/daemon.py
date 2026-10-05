"""Background D4Planner supervisor entry point."""

from __future__ import annotations

import argparse

from .runtime.pathing import UserPathManager, WindowsRegistryPathBackend
from .runtime.store import RuntimePaths
from .runtime.supervisor import Supervisor
from .runtime.windows import WindowsRuntime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="d4planner-daemon")
    parser.add_argument("--speech", action="store_true", help="Pass D4 speech through NVDA")
    parser.add_argument("--isolated", action="store_true", help="Use process-scoped controller discovery")
    parser.add_argument("--game-start-timeout", type=float, default=90.0)
    args = parser.parse_args(argv)

    paths = RuntimePaths.default()
    paths.ensure()
    runtime = WindowsRuntime(paths)
    path_manager = UserPathManager(paths, WindowsRegistryPathBackend())
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=path_manager,
        silent=not args.speech,
        isolated=args.isolated,
        game_start_timeout=args.game_start_timeout,
    )
    return supervisor.run()


if __name__ == "__main__":
    raise SystemExit(main())
