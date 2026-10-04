from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from streamops.cli import build_parser as build_streamops_parser
from streamops.server.config import ServerConfig
from streamops.server.errors import ServerConfigError
from streamops.server.main import build_parser as build_node_parser


def _namespace(**values) -> argparse.Namespace:
    defaults = {
        "host": None,
        "port": None,
        "output_index": None,
        "data_dir": None,
        "capture_timeout": None,
        "log_level": None,
    }
    return argparse.Namespace(**(defaults | values))


def test_config_uses_defaults(tmp_path: Path) -> None:
    config = ServerConfig.from_namespace(_namespace(), environ={}, repository_root=tmp_path)

    assert config.host == "0.0.0.0"
    assert config.port == 8765
    assert config.output_index == 0
    assert config.data_dir == (tmp_path / ".streamops" / "node").resolve()


def test_cli_values_override_environment(tmp_path: Path) -> None:
    config = ServerConfig.from_namespace(
        _namespace(port=8785, output_index=2, data_dir=tmp_path / "cli"),
        environ={
            "STREAMOPS_NODE_PORT": "9999",
            "STREAMOPS_NODE_OUTPUT_INDEX": "1",
            "STREAMOPS_NODE_DATA_DIR": "env",
        },
        repository_root=tmp_path,
    )

    assert config.port == 8785
    assert config.output_index == 2
    assert config.data_dir == (tmp_path / "cli").resolve()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("STREAMOPS_NODE_PORT", "0", "1 to 65535"),
        ("STREAMOPS_NODE_PORT", "nope", "1 to 65535"),
        ("STREAMOPS_NODE_OUTPUT_INDEX", "-1", "non-negative"),
        ("STREAMOPS_NODE_CAPTURE_TIMEOUT", "nan", "at most 30"),
        ("STREAMOPS_NODE_LOG_LEVEL", "verbose", "must be one of"),
    ],
)
def test_invalid_environment_is_rejected(name: str, value: str, message: str) -> None:
    with pytest.raises(ServerConfigError, match=message):
        ServerConfig.from_namespace(_namespace(), environ={name: value})


def test_streamops_and_node_alias_parse_the_same_options() -> None:
    root_args = build_streamops_parser().parse_args(
        ["runserver", "--port", "8785", "--output-index", "1", "--capture-timeout", "4"]
    )
    alias_args = build_node_parser().parse_args(
        ["--port", "8785", "--output-index", "1", "--capture-timeout", "4"]
    )

    repository_root = Path.cwd()
    root = ServerConfig.from_namespace(root_args, environ={}, repository_root=repository_root)
    alias = ServerConfig.from_namespace(alias_args, environ={}, repository_root=repository_root)
    assert root == alias


def test_data_directory_can_live_outside_the_source_checkout(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-node-data"
    config = ServerConfig.from_namespace(_namespace(data_dir=outside), environ={})
    assert config.data_dir == outside.resolve()
