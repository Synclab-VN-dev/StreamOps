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


def validate_mapping(data: dict[str, Any], mode: str) -> bool:
    targets = [x for x in data.get("targets", []) if managed(x)]
    if len(targets) != 2:
        return False
    ids = [x.get("video-config") for x in targets]
    if mode == "shared":
        return ids == [OBS_ENCODER, OBS_ENCODER]
    return len(set(ids)) == 2 and all(isinstance(x, str) and x.startswith(PREFIX + "video-") for x in ids)


def parse_rate(value: Any) -> float | None:
    if not isinstance(value, str) or value in {"", "0/0", "N/A"}:
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def eval_ffprobe(payload: dict[str, Any], width: int | None, height: int | None, fps: float | None) -> list[Result]:
    streams = payload.get("streams", []) if isinstance(payload, dict) else []
    video = next((x for x in streams if isinstance(x, dict) and x.get("codec_type") == "video"), None)
    audio = next((x for x in streams if isinstance(x, dict) and x.get("codec_type") == "audio"), None)
    out = [Result("VIDEO_PRESENT", "PASS" if video else "FAIL", "video found" if video else "video missing"), Result("AUDIO_PRESENT", "PASS" if audio else "FAIL", "audio found" if audio else "audio missing")]
    if not video:
        return out + [Result("VIDEO_CODEC", "FAIL", "no video"), Result("VIDEO_RESOLUTION", "FAIL", "no video"), Result("VIDEO_FPS", "FAIL", "no video")]
    codec = str(video.get("codec_name") or "").lower()
    out.append(Result("VIDEO_CODEC", "PASS" if codec == "h264" else "FAIL", f"codec={codec or 'unknown'}"))
    actual = (to_int(video.get("width")), to_int(video.get("height")))
    if width is None or height is None:
        out.append(Result("VIDEO_RESOLUTION", "SKIP", f"actual={actual[0]}x{actual[1]}"))
    else:
        out.append(Result("VIDEO_RESOLUTION", "PASS" if actual == (width, height) else "FAIL", f"actual={actual[0]}x{actual[1]}, expected={width}x{height}"))
    actual_fps = parse_rate(video.get("r_frame_rate") or video.get("avg_frame_rate"))
    if fps is None or actual_fps is None:
        out.append(Result("VIDEO_FPS", "SKIP", f"actual={actual_fps}"))
    else:
        out.append(Result("VIDEO_FPS", "PASS" if abs(actual_fps - fps) <= 0.5 else "FAIL", f"actual={actual_fps:g}, expected={fps:g}"))
    return out


def summarize(samples: list[Sample], cpus: int | None = None) -> dict[str, Any]:
    cpus = max(1, cpus or os.cpu_count() or 1)
    cpu, net = [], []
    for left, right in zip(samples, samples[1:]):
        dt = right.ts - left.ts
        if dt <= 0:
            continue
        if left.cpu_s is not None and right.cpu_s is not None:
            cpu.append(max(0.0, right.cpu_s-left.cpu_s) / dt / cpus * 100)
        if left.net_bytes is not None and right.net_bytes is not None:
            net.append(max(0, right.net_bytes-left.net_bytes) * 8 / dt / 1_000_000)
    return {
        "samples": len(samples),
        "obs_cpu_percent": stats(cpu),
        "obs_working_set_mb": stats([x.ws_bytes/1024/1024 for x in samples if x.ws_bytes is not None]),
        "network_tx_mbps": stats(net),
        "gpu_util_percent": stats([x.gpu for x in samples if x.gpu is not None]),
        "encoder_util_percent": stats([x.enc for x in samples if x.enc is not None]),
    }


def stats(values: list[float]) -> dict[str, float | None]:
    values = sorted(float(x) for x in values if math.isfinite(float(x)))
    if not values:
        return {"avg": None, "max": None, "p95": None}
    idx = max(0, math.ceil(len(values)*0.95)-1)
    return {"avg": round(statistics.fmean(values), 3), "max": round(max(values), 3), "p95": round(values[idx], 3)}


class Http:
    def __init__(self, base: str, secrets_: tuple[str, ...], timeout: float):
        self.base, self.secrets, self.timeout = base.rstrip("/"), secrets_, timeout
    def call(self, method: str, path: str) -> Any:
        try:
            with urlopen(Request(self.base+path, method=method, headers={"Accept":"application/json"}), timeout=self.timeout) as r:
                raw, status = r.read().decode(errors="replace"), r.status
        except HTTPError as e:
            raw = e.read().decode(errors="replace")
            raise PocError(f"HTTP {e.code} {method} {path}: {redact(raw[:300], self.secrets)}") from None
        except (URLError, OSError, TimeoutError) as e:
            raise PocError(f"HTTP {method} {path} failed: {redact(str(e), self.secrets)}") from None
        if status < 200 or status >= 300:
            raise PocError(f"HTTP {status} {method} {path}")
        return json.loads(raw) if raw.strip() else None
    def get(self, path: str) -> Any: return self.call("GET", path)
    def post(self, path: str) -> Any: return self.call("POST", path)


class MediaMTX:
    def __init__(self, exe: Path, root: Path, rtmp: int, api: int):
        self.exe, self.root, self.rtmp, self.api, self.proc = exe, root, rtmp, api, None
    @property
    def server(self) -> str: return f"rtmp://127.0.0.1:{self.rtmp}/live"
    def start(self, timeout: float) -> None:
        if self.proc is not None and self.proc.poll() is None: return
        if not self.exe.is_file(): raise PocError(f"MediaMTX missing: {self.exe}")
        if tcp(self.rtmp) or tcp(self.api): raise PocError(f"MediaMTX port conflict ({self.rtmp}/{self.api})")
        self.root.mkdir(parents=True, exist_ok=True)
        cfg = self.root/"mediamtx.yml"
        cfg.write_text(f'''logLevel: warn
logDestinations: [stdout]
api: true
apiAddress: 127.0.0.1:{self.api}
metrics: false
pprof: false
playback: false
rtsp: false
rtmp: true
rtmpEncryption: "no"
rtmpAddress: 127.0.0.1:{self.rtmp}
hls: false
webrtc: false
srt: false
moq: false
paths:
  all_others:
''', encoding="utf-8")
        self.proc = subprocess.Popen([str(self.exe), str(cfg)], cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None: raise PocError("MediaMTX exited during startup")
            if tcp(self.rtmp) and tcp(self.api): return
            time.sleep(.2)
        raise PocError("MediaMTX startup timeout")
    def stop(self) -> None:
        p, self.proc = self.proc, None
        if p is None or p.poll() is not None: return
        p.terminate()
        try: p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill(); p.wait(3)
    def snapshot(self, path: str, timeout: float) -> dict[str, int]:
        data = get_json(f"http://127.0.0.1:{self.api}/v3/rtmp/conns/list", timeout)
        items = data.get("items", []) if isinstance(data, dict) else []
        matches = [x for x in items if isinstance(x, dict) and x.get("state") == "publish" and str(x.get("path") or "").strip("/") == path.strip("/")]
        return {"count": len(matches), "bytes": sum(int(number(x.get("bytesReceived")) or 0) for x in matches)}
    def wait(self, path: str, count: int, timeout: float) -> dict[str, int]:
        deadline, last = time.monotonic()+timeout, {"count":-1,"bytes":0}
        while time.monotonic() < deadline:
            try: last = self.snapshot(path, min(2.0, timeout))
            except Exception: pass
            if last["count"] == count: return last
            time.sleep(.25)
        raise PocError(f"receiver {self.rtmp} publisher_count={last['count']} expected={count}")


class Runner:
    def __init__(self, args: argparse.Namespace):
        self.a_key, self.b_key, self.trigger_key = [PREFIX+x+"-"+secrets.token_hex(8) for x in ("a","b","trigger")]
        self.secrets = (self.a_key, self.b_key, self.trigger_key)
        self.http = Http(args.base_url, self.secrets, args.timeout)
        root = args.evidence/"runtime"
        self.a = MediaMTX(args.mediamtx, root/"a", args.rtmp_a, args.api_a)
        self.b = MediaMTX(args.mediamtx, root/"b", args.rtmp_b, args.api_b)
        self.ta, self.tb = Target("issue34-a", self.a.server, self.a_key), Target("issue34-b", self.b.server, self.b_key)
        self.args, self.results, self.metrics, self.probes = args, [], {}, {}
        self.obs = None; self.cfg_path = None; self.cfg_raw = None; self.service = None; self.identity = None; self.scene_hashes = {}
    def record(self, name: str, status: str, evidence: str): self.results.append(Result(name, status, redact(evidence, self.secrets)))
    def require(self, ok: bool, name: str, evidence: str):
        self.record(name, "PASS" if ok else "FAIL", evidence)
        if not ok: raise PocError(evidence)
    def connect_obs(self):
        if self.obs:
            try: self.obs.close()
            except Exception: pass
        from streamops.server.obs.client import ObsClient
        self.obs = ObsClient.from_env(); self.obs.connect()
    def lifecycle(self, action: str):
        self.http.post(f"/api/v1/obs/process/{action}"); wait_process(self.http, "READY" if action == "start" else "STOPPED", self.args.live_timeout)
    def apply(self, data: dict[str, Any]):
        try: stop_stream(self.obs, self.args.live_timeout)
        except Exception: pass
        self.lifecycle("stop")
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text(json.dumps(data, separators=(",",":"), ensure_ascii=False), encoding="utf-8")
        self.lifecycle("start"); self.connect_obs(); self.check_identity()
    def local_main(self): self.obs.set_stream_service_settings("rtmp_custom", {"server": self.a.server, "key": self.trigger_key})
    def check_identity(self):
        if not self.identity: return
        now = obs_identity(self.obs)
        if now != self.identity: raise PocError("OBS profile/scene identity changed")
    def baseline(self):
        st = self.http.get("/api/v1/obs/process/status"); out = st.get("output", {}); ws = st.get("websocket", {})
        self.require(st.get("state")=="READY" and ws.get("connected") is True and not out.get("streaming") and not out.get("recording"), "AC-A-01", "OBS READY, websocket connected, outputs idle")
        pl = self.http.get("/api/v1/obs/plugins/obs-multi-rtmp")
        self.require(pl.get("state")=="LOADED" and pl.get("loaded") is True, "AC-A-01_PLUGIN", "obs-multi-rtmp LOADED")
        self.connect_obs(); self.cfg_path = self.args.plugin_config or resolve_config(self.obs)
        self.cfg_raw = self.cfg_path.read_bytes() if self.cfg_path.exists() else None
        base = load_config(self.cfg_raw)
        self.require(not [x for x in base.get("targets",[]) if not managed(x)], "SAFETY_EXISTING_TARGETS", "no non-issue34 target may be configured during POC")
        self.service, self.identity = self.obs.get_stream_service_settings(), obs_identity(self.obs)
        self.scene_hashes = hashes(scene_root())
    def main_only(self):
        self.apply(strip_managed(load_config(self.cfg_raw))); self.metrics["idle"] = summarize(samples(self.args.metric_seconds, self.args.metric_interval))
        self.local_main(); self.obs.start_stream()
        try: wait_stream(self.obs, True, self.args.live_timeout); self.metrics["main-only"] = summarize(samples(self.args.metric_seconds, self.args.metric_interval))
        finally: stop_stream(self.obs, self.args.live_timeout)
        self.record("RESOURCE_MAIN_BASELINE", "PASS", "idle and main-only metrics captured")
    def mode(self, mode: str, cycles: int):
        data = build_config(load_config(self.cfg_raw), self.ta, self.tb, mode=mode, encoder=self.args.independent_encoder)
        self.require(validate_mapping(data, mode), "CI_"+mode.upper()+"_MAPPING", "deterministic encoder mapping")
        self.apply(data); self.local_main()
        video = self.obs.get_video_settings()
        if mode == "shared":
            w,h = to_int(video.get("outputWidth")), to_int(video.get("outputHeight")); n,d=number(video.get("fpsNumerator")),number(video.get("fpsDenominator")); fps=n/d if n is not None and d else None
        else: w,h,fps=1280,720,None
        for i in range(1, cycles+1): self.cycle(mode,i,w,h,fps)
        if mode == "shared": self.fault(w,h,fps)
    def cycle(self, mode: str, i: int, w: int|None, h: int|None, fps: float|None):
        self.obs.start_stream(); wait_stream(self.obs, True, self.args.live_timeout)
        try:
            sa,sb=self.a.wait(self.ta.path,1,self.args.live_timeout),self.b.wait(self.tb.path,1,self.args.live_timeout)
            self.require(sa["count"]==sb["count"]==1, f"{mode}_{i}_DUAL_LIVE", "one publisher on A and B")
            pa,pb=probe(self.args.ffprobe,self.ta.url,self.secrets,self.args.timeout),probe(self.args.ffprobe,self.tb.url,self.secrets,self.args.timeout)
            for side,payload in (("A",pa),("B",pb)):
                for r in eval_ffprobe(payload,w,h,fps): self.record(f"{mode}_{i}_{side}_{r.name}",r.status,r.evidence)
                self.probes[f"{mode}-{i}-{side.lower()}"]=sanitize(payload,self.secrets)
            self.metrics[mode]=summarize(samples(self.args.metric_seconds,self.args.metric_interval))
            self.require(self.a.snapshot(self.ta.path,self.args.timeout)["count"]==1 and self.b.snapshot(self.tb.path,self.args.timeout)["count"]==1, f"{mode}_{i}_NO_DUPLICATE", "publisher_count remains exactly one")
        finally:
            stop_stream(self.obs,self.args.live_timeout); self.a.wait(self.ta.path,0,self.args.live_timeout); self.b.wait(self.tb.path,0,self.args.live_timeout); self.record(f"{mode}_{i}_STOP","PASS","both publishers stopped")
    def fault(self,w,h,fps):
        self.obs.start_stream(); wait_stream(self.obs,True,self.args.live_timeout); self.a.wait(self.ta.path,1,self.args.live_timeout); self.b.wait(self.tb.path,1,self.args.live_timeout)
        before=self.a.snapshot(self.ta.path,self.args.timeout); self.b.stop(); time.sleep(2); after=self.a.snapshot(self.ta.path,self.args.timeout)
        ok=after["count"]==1 and after["bytes"]>before["bytes"] and all(x.status!="FAIL" for x in eval_ffprobe(probe(self.args.ffprobe,self.ta.url,self.secrets,self.args.timeout),w,h,fps))
        self.record("AC-A-07_FAULT_ISOLATION","PASS" if ok else "FAIL",f"A publisher={after['count']}; bytes_progress={after['bytes']>before['bytes']}")
        self.b.start(self.args.timeout)
        try: self.b.wait(self.tb.path,1,min(15,self.args.live_timeout)); self.record("B_RECONNECT_BEHAVIOR","PASS","B auto-reconnected")
        except Exception: self.record("B_RECONNECT_BEHAVIOR","SKIP","B did not auto-reconnect within observation window")
        stop_stream(self.obs,self.args.live_timeout); self.a.wait(self.ta.path,0,self.args.live_timeout)
        try: self.b.wait(self.tb.path,0,self.args.live_timeout)
        except Exception: pass
    def restore(self):
        errors=[]
        try:
            if self.obs and self.service:
                try: stop_stream(self.obs,self.args.live_timeout); self.obs.set_stream_service_settings(str(self.service.get("streamServiceType") or ""),dict(self.service.get("streamServiceSettings") or {}))
                except Exception as e: errors.append("stream service: "+redact(str(e),self.secrets))
            if self.cfg_path:
                try:
                    self.lifecycle("stop")
                    if self.cfg_raw is None: self.cfg_path.unlink(missing_ok=True)
                    else: self.cfg_path.write_bytes(self.cfg_raw)
                    self.lifecycle("start"); self.connect_obs(); self.check_identity()
                except Exception as e: errors.append("plugin config: "+redact(str(e),self.secrets))
            self.a.stop(); self.b.stop()
            if self.scene_hashes and hashes(scene_root()) != self.scene_hashes: errors.append("scene collection hashes changed")
            st=self.http.get("/api/v1/obs/process/status")
            if st.get("state")!="READY" or st.get("websocket",{}).get("connected") is not True: errors.append("final OBS not READY")
        except Exception as e: errors.append(redact(str(e),self.secrets))
        self.record("AC-A-12_RESTORE","FAIL" if errors else "PASS","; ".join(errors) if errors else "config/service/scenes restored and OBS READY")
    def write(self):
        overall="FAIL" if any(x.status=="FAIL" for x in self.results) else ("PASS WITH LIMITATION" if any(x.status=="SKIP" for x in self.results if x.name=="B_RECONNECT_BEHAVIOR") else "PASS")
        self.args.evidence.mkdir(parents=True,exist_ok=True)
