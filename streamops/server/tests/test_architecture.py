from __future__ import annotations

import ast
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1]


def test_server_has_no_imports_from_other_streamops_modules() -> None:
    violations: list[str] = []
    for path in SERVER_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name == "streamops" or (name.startswith("streamops.") and not name.startswith("streamops.server")):
                    violations.append(f"{path.relative_to(SERVER_ROOT)} imports {name}")

    assert violations == []


def test_server_runtime_does_not_depend_on_checkout_scripts_or_plugin_source_paths() -> None:
    violations = []
    for path in SERVER_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if "scripts/devices/a-windows" in source or "scripts\\devices\\a-windows" in source:
            violations.append(f"{path.relative_to(SERVER_ROOT)} references deployment scripts")
        if path.parent.name == "obs_plugin" and ("__file__" in source or ".parents[" in source):
            violations.append(f"{path.relative_to(SERVER_ROOT)} discovers resources from source paths")

    assert violations == []
