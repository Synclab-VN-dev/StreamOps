#!/usr/bin/env python3
"""Real-A acceptance runner for issue #34 (OBS direct dual RTMP POC).

This is test tooling, not a StreamOps multistream runtime API. It temporarily
uses two isolated local MediaMTX receivers, patches only issue34-* plugin config,
drives OBS with existing lifecycle + obs-websocket, writes sanitized evidence,
and restores the original state in a finally block.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import socket
import statistics
import subprocess
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PREFIX = "issue34-"
OBS_ENCODER = "<OBS_STREAMING_ENCODER>"

class PocError(RuntimeError):
    pass

@dataclass(frozen=True)
class Target:
    name: str
    server: str
    key: str
    @property
    def url(self) -> str:
        return f"{self.server.rstrip('/')}/{self.key}"
    @property
    def path(self) -> str:
        rest = self.server.split("//", 1)[-1].split("/", 1)
        app = rest[1].strip("/") if len(rest) == 2 else ""
        return "/".join(x for x in (app, self.key) if x)

@dataclass(frozen=True)
class Result:
    name: str
    status: str
    evidence: str

@dataclass(frozen=True)
class Sample:
    ts: float
    cpu_s: float | None
    ws_bytes: int | None
    net_bytes: int | None
    gpu: float | None
    enc: float | None


def redact(text: str, secrets_: Iterable[str]) -> str:
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def sanitize(value: Any, secrets_: Iterable[str]) -> Any:
    secrets_ = tuple(x for x in secrets_ if x)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if str(key).casefold() in {"key", "token", "password", "credential", "stream_key", "streamkey"}:
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = sanitize(item, secrets_)
        return out
    if isinstance(value, list):
        return [sanitize(x, secrets_) for x in value]
    return redact(value, secrets_) if isinstance(value, str) else value


def managed(item: Any) -> bool:
    return isinstance(item, dict) and str(item.get("id") or "").startswith(PREFIX)


def strip_managed(base: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(base)
    for key in ("targets", "video_configs", "audio_configs"):
        data[key] = [x for x in data.get(key, []) if not managed(x)]
    return data


def build_config(base: dict[str, Any], a: Target, b: Target, *, mode: str, encoder: str = "obs_x264") -> dict[str, Any]:
    if mode not in {"independent", "shared"}:
        raise ValueError("mode must be independent or shared")
    data = strip_managed(base)
    if mode == "shared":
        video_ids = (OBS_ENCODER, OBS_ENCODER)
    else:
        video_ids = (PREFIX + "video-a", PREFIX + "video-b")
        for ident in video_ids:
            data["video_configs"].append({"id": ident, "encoder": encoder, "param": {}, "resolution": "1280x720", "fps-denumerator": 1})
    for suffix, target, video_id in (("a", a, video_ids[0]), ("b", b, video_ids[1])):
        data["targets"].append({
            "id": PREFIX + "target-" + suffix,
            "name": target.name,
            "protocol": "RTMP",
            "service-param": {"server": target.server, "key": target.key},
            "output-param": {},
            "sync-start": True,
            "sync-stop": True,
            "video-config": video_id,
            "audio-config": OBS_ENCODER,
        })
    return data
