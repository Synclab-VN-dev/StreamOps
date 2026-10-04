import importlib.util
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    path = ROOT / "tools" / "build_nvda_addon.py"
    spec = importlib.util.spec_from_file_location("build_nvda_addon", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_nvda_addon_contains_runtime_layout(tmp_path):
    builder = _load_builder()
    output = tmp_path / "d4plannerCapture.nvda-addon"
    builder.build(output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())

    assert "manifest.ini" in names
    assert "globalPlugins/d4plannerCapture/__init__.py" in names
    assert "globalPlugins/d4plannerCapture/core.py" in names
    assert "doc/en/readme.html" in names
    assert not any(name.startswith("addon/") for name in names)
