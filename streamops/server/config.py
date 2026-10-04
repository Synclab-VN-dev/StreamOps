"""Configuration parsing for the standalone node server."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
from typing import Mapping

from .errors import ServerConfigError


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_OUTPUT_INDEX = 0
DEFAULT_CAPTURE_TIMEOUT = 3.0
DEFAULT_LOG_LEVEL = "info"
LOG_LEVELS = ("critical", "error", "warning", "info", "debug", "trace")


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    output_index: int
    data_dir: Path
    capture_timeout: float
    log_level: str

    @classmethod
    def from_namespace(
        cls,
        namespace: argparse.Namespace,
        *,
        environ: Mapping[str, str] | None = None,
        repository_root: Path | None = None,
    ) -> "ServerConfig":
        env = os.environ if environ is None else environ
        root = repository_root.resolve() if repository_root is not None else None
        host = _source(namespace.host, env, "STREAMOPS_NODE_HOST", DEFAULT_HOST)
        port = _parse_port(_source(namespace.port, env, "STREAMOPS_NODE_PORT", DEFAULT_PORT))
        output_index = _parse_output_index(
            _source(namespace.output_index, env, "STREAMOPS_NODE_OUTPUT_INDEX", DEFAULT_OUTPUT_INDEX)
        )
        timeout = _parse_timeout(
            _source(namespace.capture_timeout, env, "STREAMOPS_NODE_CAPTURE_TIMEOUT", DEFAULT_CAPTURE_TIMEOUT)
        )
        log_level = str(
            _source(namespace.log_level, env, "STREAMOPS_NODE_LOG_LEVEL", DEFAULT_LOG_LEVEL)
        ).lower()
        if log_level not in LOG_LEVELS:
            raise ServerConfigError(
                f"STREAMOPS_NODE_LOG_LEVEL must be one of: {', '.join(LOG_LEVELS)}."
            )

        host = str(host).strip()
        if not host or any(character.isspace() for character in host):
            raise ServerConfigError("Server host must be a non-empty hostname or IP address.")

        data_dir_raw = _source(
            namespace.data_dir,
            env,
            "STREAMOPS_NODE_DATA_DIR",
            (root / ".streamops" / "node") if root else _default_data_dir(env),
        )
        data_dir_value = Path(os.path.expandvars(os.path.expanduser(str(data_dir_raw))))
        data_dir = (data_dir_value if data_dir_value.is_absolute() else Path.cwd() / data_dir_value).resolve()
        if data_dir == Path(data_dir.anchor):
            raise ServerConfigError("STREAMOPS_NODE_DATA_DIR cannot be a filesystem root.")
        return cls(
            host=host,
            port=port,
            output_index=output_index,
            data_dir=data_dir,
            capture_timeout=timeout,
            log_level=log_level,
        )


def add_server_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help=f"Bind host (default: {DEFAULT_HOST}).")
    parser.add_argument("--port", type=_argparse_port, help=f"Bind port (default: {DEFAULT_PORT}).")
    parser.add_argument(
        "--output-index",
        type=_argparse_output_index,
        help=f"DXGI output index (default: {DEFAULT_OUTPUT_INDEX}).",
    )
    parser.add_argument("--data-dir", type=Path, help="Runtime data directory.")
    parser.add_argument(
        "--capture-timeout",
        type=_argparse_timeout,
        help=f"Capture timeout in seconds (default: {DEFAULT_CAPTURE_TIMEOUT:g}).",
    )
    parser.add_argument("--log-level", choices=LOG_LEVELS, help=f"Log level (default: {DEFAULT_LOG_LEVEL}).")


def _source(cli_value: object, env: Mapping[str, str], name: str, default: object) -> object:
    if cli_value is not None:
        return cli_value
    value = env.get(name)
    return value if value not in (None, "") else default


def _default_data_dir(environ: Mapping[str, str]) -> Path:
    if os.name == "nt":
        base = environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "StreamOps" / "node"
    state_home = environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "streamops" / "node"
    return Path.home() / ".local" / "state" / "streamops" / "node"


def _parse_port(value: object) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ServerConfigError("STREAMOPS_NODE_PORT must be an integer from 1 to 65535.") from exc
    if not 1 <= port <= 65535:
        raise ServerConfigError("STREAMOPS_NODE_PORT must be an integer from 1 to 65535.")
    return port


def _parse_output_index(value: object) -> int:
    try:
        output_index = int(value)
    except (TypeError, ValueError) as exc:
        raise ServerConfigError("STREAMOPS_NODE_OUTPUT_INDEX must be a non-negative integer.") from exc
    if output_index < 0:
        raise ServerConfigError("STREAMOPS_NODE_OUTPUT_INDEX must be a non-negative integer.")
    return output_index


def _parse_timeout(value: object) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ServerConfigError("STREAMOPS_NODE_CAPTURE_TIMEOUT must be greater than 0 and at most 30.") from exc
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ServerConfigError("STREAMOPS_NODE_CAPTURE_TIMEOUT must be greater than 0 and at most 30.")
    return timeout


def _argparse_port(value: str) -> int:
    try:
        return _parse_port(value)
    except ServerConfigError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _argparse_output_index(value: str) -> int:
    try:
        return _parse_output_index(value)
    except ServerConfigError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _argparse_timeout(value: str) -> float:
    try:
        return _parse_timeout(value)
    except ServerConfigError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
