"""Build the D4Planner NVDA add-on as a standard .nvda-addon ZIP archive."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ADDON_SOURCE = ROOT / "nvda-addon"
CORE_SOURCE = ROOT / "src" / "d4planner" / "capture" / "core.py"


def build(output: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="d4planner-nvda-") as temp_dir:
        staging = Path(temp_dir)
        shutil.copy2(ADDON_SOURCE / "manifest.ini", staging / "manifest.ini")

        # Source keeps NVDA files under nvda-addon/addon for repository clarity.
        # The distributable archive must expose globalPlugins/doc at its root.
        for child in (ADDON_SOURCE / "addon").iterdir():
            destination = staging / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)

        plugin_dir = staging / "globalPlugins" / "d4plannerCapture"
        shutil.copy2(CORE_SOURCE, plugin_dir / "core.py")

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "d4plannerCapture-0.2.0.nvda-addon",
    )
    args = parser.parse_args(argv)
    path = build(args.output.resolve())
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
