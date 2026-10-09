"""Create and verify a hash-pinned StreamOps node deployment wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(root: Path) -> list[dict[str, object]]:
    result = []
    for path in sorted((root / "wheelhouse").glob("*.whl")):
        result.append({
            "relative_path": path.relative_to(root).as_posix(),
            "length": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return result


def pack(root: Path, source_commit: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise ValueError("source commit must be 40 lowercase hex characters")
    files = _files(root)
    app = [item for item in files if PurePosixPath(str(item["relative_path"])).name.startswith("streamops-")]
    if len(app) != 1:
        raise ValueError("wheelhouse must contain exactly one StreamOps wheel")
    payload = {"schema_version": 1, "source_commit": source_commit, "files": files}
    (root / "deployment-manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


def verify(root: Path, expected_commit: str) -> None:
    manifest = json.loads((root / "deployment-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("source_commit") != expected_commit:
        raise ValueError("deployment manifest identity mismatch")
    expected = manifest.get("files")
    if not isinstance(expected, list) or expected != _files(root):
        raise ValueError("deployment wheelhouse differs from its manifest")
    for item in expected:
        relative = PurePosixPath(str(item.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("wheelhouse",):
            raise ValueError("unsafe deployment manifest path")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("pack", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    if args.command == "pack":
        pack(args.root, args.source_commit)
    else:
        verify(args.root, args.source_commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
