import shutil

import d4planner
from d4planner.cli import build_parser


def test_runtime_package_version_and_cli_entrypoint_available():
    assert d4planner.__version__ == "0.2.0"
    # Editable install is performed by CI before this test suite.
    assert shutil.which("d4planner") is not None
    assert build_parser().prog == "d4planner"
