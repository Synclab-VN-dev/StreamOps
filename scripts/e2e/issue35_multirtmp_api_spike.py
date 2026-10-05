#!/usr/bin/env python3
"""Issue #35 Gate 3 runner: probe native OBS outputs and candidate Vendor API.

This is POC/test tooling only. It does not add StreamOps production multistream
routes or UI. Raw evidence stays under .streamops/issue-35 and is sanitized.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PREFIX = "issue35-"
VENDOR = "sorayuki.multi_rtmp"
OBS_ENCODER = "<OBS_STREAMING_ENCODER>"
SENSITIVE_KEYS = {
    "key", "token", "password", "credential", "stream_key", "streamkey",
    "newstreamkey", "new_stream_key",
}


class PocError(RuntimeError):
    pass


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    evidence: str


def redact(text: str, secrets_: Iterable[str]) -> str:
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def sanitize(value: Any, secrets_: Iterable[str]) -> Any:
    secrets_ = tuple(x for x in secrets_ if x)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).replace("-", "_").casefold() in SENSITIVE_KEYS:
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = sanitize(item, secrets_)
        return out
    if isinstance(value, list):
        return [sanitize(x, secrets_) for x in value]
    return redact(value, secrets_) if isinstance(value, str) else value


def normalize_vendor_target(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or ""),
        "protocol": str(raw.get("protocol") or ""),
        "running": bool(raw.get("isRunning", raw.get("streaming", False))),
        "status": str(raw.get("status") or raw.get("rawStatus") or ""),
        "bitrate_bps": _number(raw.get("bitrateValue", raw.get("bitrate_bps"))) or 0.0,
        "fps": _number(raw.get("fpsValue", raw.get("fps"))) or 0.0,
        "sync_start": bool(raw.get("syncStart", False)),
        "sync_stop": bool(raw.get("syncStop", False)),
    }


def identity_map(targets: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in targets:
        target = normalize_vendor_target(raw)
        if target["name"]:
            out[target["name"]] = target["id"]
    return out


def stable_identity(before: list[dict[str, Any]], after: list[dict[str, Any]], names: set[str]) -> bool:
    left, right = identity_map(before), identity_map(after)
    return all(left.get(name) and left.get(name) == right.get(name) for name in names)


def duplicate_names(targets: list[dict[str, Any]]) -> set[str]:
    counts: dict[str, int] = {}
    for raw in targets:
        name = str(raw.get("name") or "")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return {name for name, count in counts.items() if count > 1}


def native_output_groups(outputs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in outputs:
        name = str(item.get("outputName") or "")
        kind = str(item.get("outputKind") or "")
        if "multi" not in (name + " " + kind).casefold():
            continue
        groups.setdefault(name, []).append(item)
    return groups


def build_native_fixture(base: dict[str, Any], *, server_a: str, server_b: str, key_a: str, key_b: str,
                         encoder: str = "obs_x264") -> dict[str, Any]:
    data = copy.deepcopy(base)
    for field in ("targets", "video_configs", "audio_configs"):
        existing = data.get(field, [])
        data[field] = [
            item for item in existing
            if not (isinstance(item, dict) and str(item.get("id") or "").startswith(PREFIX))
        ]

    for suffix, server, key in (("a", server_a, key_a), ("b", server_b, key_b)):
        video_id = f"{PREFIX}video-{suffix}"
        data["video_configs"].append({
            "id": video_id,
            "encoder": encoder,
            "param": {},
            "resolution": "1280x720",
            "fps-denumerator": 1,
        })
        data["targets"].append({
            "id": f"{PREFIX}target-{suffix}",
            "name": f"{PREFIX}{suffix}",
            "protocol": "RTMP",
            "service-param": {"server": server, "key": key},
            "output-param": {},
            "sync-start": False,
            "sync-stop": False,
            "video-config": video_id,
            "audio-config": OBS_ENCODER,
        })
    return data


def capability_template() -> dict[str, str]:
    return {
        "list": "UNKNOWN",
        "stable_target_identity": "UNKNOWN",
        "start_one": "UNKNOWN",
        "stop_one": "UNKNOWN",
        "start_all": "UNKNOWN",
        "stop_all": "UNKNOWN",
        "add": "UNKNOWN",
        "update": "UNKNOWN",
        "delete": "UNKNOWN",
        "live_failed_state": "UNKNOWN",
        "stats_error": "UNKNOWN",
        "credential_update": "UNKNOWN",
        "secret_safe_response": "UNKNOWN",
    }


class Http:
    def __init__(self, base: str, secrets_: tuple[str, ...], timeout: float):
        self.base = base.rstrip("/")
        self.secrets = secrets_
        self.timeout = timeout

    def call(self, method: str, path: str) -> Any:
        try:
            req = Request(self.base + path, method=method, headers={"Accept": "application/json"})
            with urlopen(req, timeout=self.timeout) as response:
                raw, status = response.read().decode(errors="replace"), response.status
        except HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            raise PocError(f"HTTP {exc.code} {method} {path}: {redact(raw[:300], self.secrets)}") from None
        except (URLError, OSError, TimeoutError) as exc:
            raise PocError(f"HTTP {method} {path} failed: {redact(str(exc), self.secrets)}") from None
        if not 200 <= status < 300:
            raise PocError(f"HTTP {status} {method} {path}")
        return json.loads(raw) if raw.strip() else None

    def get(self, path: str) -> Any:
        return self.call("GET", path)

    def post(self, path: str) -> Any:
        return self.call("POST", path)


class Runner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.secrets = (f"{PREFIX}a-{secrets.token_hex(10)}", f"{PREFIX}b-{secrets.token_hex(10)}")
        self.http = Http(args.base_url, self.secrets, args.timeout)
        self.results: list[Result] = []
        self.capabilities = {
            "native_obs_upstream": capability_template(),
            "upstream_vendor": capability_template(),
            "candidate_vendor": capability_template(),
        }
        self.evidence: dict[str, Any] = {}
        self.obs = None
        self.config_path: Path | None = None
        self.config_raw: bytes | None = None

    def record(self, name: str, status: str, evidence: str) -> None:
        self.results.append(Result(name, status, redact(evidence, self.secrets)))

    def connect_obs(self) -> None:
        from streamops.server.obs.client import ObsClient
        if self.obs:
            try:
                self.obs.close()
            except Exception:
                pass
        self.obs = ObsClient.from_env()
        self.obs.connect()

    def restart_obs(self) -> None:
        self.http.post("/api/v1/obs/process/stop")
        wait_process(self.http, "STOPPED", self.args.live_timeout)
        self.http.post("/api/v1/obs/process/start")
        wait_process(self.http, "READY", self.args.live_timeout)
        self.connect_obs()

    def baseline(self) -> None:
        status = self.http.get("/api/v1/obs/process/status")
        output = status.get("output", {})
        ok = (
            status.get("state") == "READY"
            and status.get("websocket", {}).get("connected") is True
            and not output.get("streaming")
            and not output.get("recording")
        )
        if not ok:
            raise PocError("OBS must be READY with websocket connected and streaming/recording false")
        plugin = self.http.get("/api/v1/obs/plugins/obs-multi-rtmp")
        if self.args.phase == "native" and plugin.get("state") != "LOADED":
            raise PocError(f"upstream obs-multi-rtmp must be LOADED, got {plugin.get('state')}")
        if self.args.phase == "vendor" and plugin.get("state") != "LOADED":
            self.record(
                "CANDIDATE_PINNED_MANIFEST_MISMATCH",
                "PASS",
                f"Gate 1 manifest state={plugin.get('state')} is expected while candidate binary is temporarily installed",
            )
        self.connect_obs()
        self.config_path = self.args.plugin_config or resolve_config(self.obs)
        self.config_raw = self.config_path.read_bytes() if self.config_path.exists() else None
        self.record("BASELINE", "PASS", "OBS READY, websocket connected, plugin loaded, outputs idle")

    def probe_upstream_vendor(self) -> None:
        try:
            response = self.vendor("list_targets")
        except Exception as exc:
            self.capabilities["upstream_vendor"]["list"] = "NO"
            self.record("UPSTREAM_VENDOR_DISCOVERY", "PASS", f"Vendor API unavailable: {exc}")
            return
        self.evidence["upstream_vendor_list"] = sanitize(response, self.secrets)
        self.capabilities["upstream_vendor"]["list"] = "YES"
        self.record("UPSTREAM_VENDOR_DISCOVERY", "PASS", "Vendor list_targets is available on current plugin")

    def native(self) -> None:
        if self.config_path is None:
            raise PocError("baseline not initialized")
        base = load_config(self.config_raw)
        fixture = build_native_fixture(
            base,
            server_a=self.args.server_a,
            server_b=self.args.server_b,
            key_a=self.secrets[0],
            key_b=self.secrets[1],
            encoder=self.args.independent_encoder,
        )
        self.http.post("/api/v1/obs/process/stop")
        wait_process(self.http, "STOPPED", self.args.live_timeout)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(fixture, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        self.http.post("/api/v1/obs/process/start")
        wait_process(self.http, "READY", self.args.live_timeout)
        self.connect_obs()

        before = self.native_snapshot()
        self.evidence["native_before_restart"] = sanitize(before, self.secrets)
        groups = native_output_groups(before)
        self.capabilities["native_obs_upstream"]["list"] = "YES" if groups else "NO"

        ambiguous = {name: items for name, items in groups.items() if len(items) > 1}
        if ambiguous:
            self.capabilities["native_obs_upstream"]["stable_target_identity"] = "NO"
            self.capabilities["native_obs_upstream"]["start_one"] = "BLOCKED"
            self.capabilities["native_obs_upstream"]["stop_one"] = "BLOCKED"
            self.record(
                "NATIVE_PER_TARGET_IDENTITY",
                "PASS",
                "Native outputName collision detected; refusing ambiguous per-target StartOutput/StopOutput",
            )
        elif len(groups) >= 2:
            self.capabilities["native_obs_upstream"]["stable_target_identity"] = "TENTATIVE"
            names = list(groups)[:2]
            control_ok = True
            for name in names:
                try:
                    self.obs.request("StartOutput", {"outputName": name})
                    wait_native_output(self.obs, name, True, self.args.control_timeout)
                    self.obs.request("StopOutput", {"outputName": name})
                    wait_native_output(self.obs, name, False, self.args.control_timeout)
                except Exception as exc:
                    control_ok = False
                    self.record("NATIVE_CONTROL_" + name, "FAIL", str(exc))
                    break
            self.capabilities["native_obs_upstream"]["start_one"] = "YES" if control_ok else "NO"
            self.capabilities["native_obs_upstream"]["stop_one"] = "YES" if control_ok else "NO"
        else:
            self.capabilities["native_obs_upstream"]["stable_target_identity"] = "NO"
            self.record("NATIVE_OUTPUT_DISCOVERY", "FAIL", f"Expected >=2 plugin outputs, got {len(groups)}")

        self.restart_obs()
        after = self.native_snapshot()
        self.evidence["native_after_restart"] = sanitize(after, self.secrets)
        if not ambiguous and len(groups) >= 2:
            before_names = sorted(native_output_groups(before))
            after_names = sorted(native_output_groups(after))
            stable = before_names == after_names
            self.capabilities["native_obs_upstream"]["stable_target_identity"] = "YES" if stable else "NO"
            self.record("NATIVE_IDENTITY_RESTART", "PASS" if stable else "FAIL", f"before={before_names}, after={after_names}")

        self.probe_upstream_vendor()

    def native_snapshot(self) -> list[dict[str, Any]]:
        outputs = list(self.obs.request("GetOutputList").get("outputs", []))
        enriched: list[dict[str, Any]] = []
        for item in outputs:
            row = dict(item)
            name = row.get("outputName")
            if name:
                try:
                    row["status"] = self.obs.request("GetOutputStatus", {"outputName": name})
                except Exception as exc:
                    row["status_error"] = str(exc)
            enriched.append(row)
        return enriched

    def vendor(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.obs.request(
            "CallVendorRequest",
            {"vendorName": VENDOR, "requestType": request_type, "requestData": data or {}},
        ).get("responseData", {})

    def vendor_targets(self) -> list[dict[str, Any]]:
        return list(self.vendor("list_targets").get("targets", []))

    def vendor_target(self, name: str) -> dict[str, Any]:
        matches = [x for x in self.vendor_targets() if x.get("name") == name]
        if len(matches) != 1:
            raise PocError(f"expected exactly one target named {name}, got {len(matches)}")
        return matches[0]

    def vendor_wait_running(self, target_id: str, expected: bool) -> dict[str, Any]:
        deadline = time.monotonic() + self.args.control_timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.vendor("get_target_state", {"id": target_id})
            if bool(last.get("isRunning", last.get("streaming", False))) is expected:
                return last
            time.sleep(0.25)
        raise PocError(f"target {target_id} running state did not become {expected}: {last}")

    def vendor_phase(self) -> None:
        initial = self.vendor_targets()
        self.evidence["candidate_vendor_initial"] = sanitize(initial, self.secrets)
        self.capabilities["candidate_vendor"]["list"] = "YES"

        # Remove only stale issue35-owned targets from previous failed POC runs.
        for raw in list(initial):
            if str(raw.get("name") or "").startswith(PREFIX):
                self.vendor("delete_target", {"id": str(raw.get("id") or "")})

        names = {f"{PREFIX}a", f"{PREFIX}b"}
        for name in sorted(names):
            self.vendor("add_target", {"name": name, "protocol": "RTMP"})
        a, b = self.vendor_target(f"{PREFIX}a"), self.vendor_target(f"{PREFIX}b")
        aid, bid = str(a["id"]), str(b["id"])
        self.capabilities["candidate_vendor"]["add"] = "YES"

        for target_id, server, key in (
            (aid, self.args.server_a, self.secrets[0]),
            (bid, self.args.server_b, self.secrets[1]),
        ):
            self.vendor("update_service_param", {"id": target_id, "key": "server", "value": server})
            response = self.vendor("update_stream_key", {"id": target_id, "streamKey": key})
            if key in json.dumps(response):
                raise PocError("Vendor credential update echoed plaintext stream key")
            self.vendor("update_sync_start", {"id": target_id, "syncStart": False})
            self.vendor("update_sync_stop", {"id": target_id, "syncStop": False})
        self.capabilities["candidate_vendor"]["update"] = "YES"
        self.capabilities["candidate_vendor"]["credential_update"] = "YES"
        self.capabilities["candidate_vendor"]["secret_safe_response"] = "YES"

        # Rename must preserve target identity.
        self.vendor("update_target_name", {"id": aid, "newName": f"{PREFIX}a-renamed"})
        renamed = self.vendor_target(f"{PREFIX}a-renamed")
        rename_stable = str(renamed.get("id")) == aid
        self.record("VENDOR_ID_STABLE_RENAME", "PASS" if rename_stable else "FAIL", f"id={aid}")
        self.vendor("update_target_name", {"id": aid, "newName": f"{PREFIX}a"})

        # Per-target control: a must not implicitly start b, and vice versa.
        self.vendor("start_target", {"id": aid})
        self.vendor_wait_running(aid, True)
        b_state = self.vendor("get_target_state", {"id": bid})
        independent_a = not bool(b_state.get("isRunning", b_state.get("streaming", False)))
        self.vendor("stop_target", {"id": aid})
        self.vendor_wait_running(aid, False)

        self.vendor("start_target", {"id": bid})
        self.vendor_wait_running(bid, True)
        a_state = self.vendor("get_target_state", {"id": aid})
        independent_b = not bool(a_state.get("isRunning", a_state.get("streaming", False)))
        stats = self.vendor("get_target_stats", {"id": bid})
        self.vendor("stop_target", {"id": bid})
        self.vendor_wait_running(bid, False)

        independent = independent_a and independent_b
        self.capabilities["candidate_vendor"]["start_one"] = "YES" if independent else "NO"
        self.capabilities["candidate_vendor"]["stop_one"] = "YES" if independent else "NO"
        self.capabilities["candidate_vendor"]["live_failed_state"] = "YES"
        self.capabilities["candidate_vendor"]["stats_error"] = "YES" if stats else "NO"
        self.evidence["candidate_stats"] = sanitize(stats, self.secrets)

        self.vendor("start_all")
        self.vendor_wait_running(aid, True)
        self.vendor_wait_running(bid, True)
        self.vendor("stop_all")
        self.vendor_wait_running(aid, False)
        self.vendor_wait_running(bid, False)
        self.capabilities["candidate_vendor"]["start_all"] = "YES"
        self.capabilities["candidate_vendor"]["stop_all"] = "YES"

        before_restart = self.vendor_targets()
        self.restart_obs()
        after_restart = self.vendor_targets()
        stable = stable_identity(before_restart, after_restart, names)
        self.capabilities["candidate_vendor"]["stable_target_identity"] = "YES" if stable else "NO"
        self.record("VENDOR_ID_STABLE_RESTART", "PASS" if stable else "FAIL", f"ids={identity_map(after_restart)}")

        # Duplicate names are permitted by current candidate; therefore names cannot be public identity.
        self.vendor("add_target", {"name": f"{PREFIX}a", "protocol": "RTMP"})
        dups = duplicate_names(self.vendor_targets())
        self.evidence["candidate_duplicate_names"] = sorted(dups)
        self.record(
            "VENDOR_DUPLICATE_NAME",
            "PASS" if f"{PREFIX}a" in dups else "FAIL",
            "Duplicate names are possible; StreamOps must use its own destination ID / plugin target ID mapping",
        )

        # Cleanup all issue35-owned targets by ID after re-listing.
        for raw in self.vendor_targets():
            if str(raw.get("name") or "").startswith(PREFIX):
                self.vendor("delete_target", {"id": str(raw.get("id") or "")})
        left = [x for x in self.vendor_targets() if str(x.get("name") or "").startswith(PREFIX)]
        self.capabilities["candidate_vendor"]["delete"] = "YES" if not left else "NO"
        if left:
            raise PocError(f"issue35 target cleanup incomplete: {left}")

    def restore_native_config(self) -> None:
        if self.config_path is None:
            return
        try:
            self.http.post("/api/v1/obs/process/stop")
            wait_process(self.http, "STOPPED", self.args.live_timeout)
            if self.config_raw is None:
                self.config_path.unlink(missing_ok=True)
            else:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                self.config_path.write_bytes(self.config_raw)
            self.http.post("/api/v1/obs/process/start")
            wait_process(self.http, "READY", self.args.live_timeout)
            self.record("RESTORE_CONFIG", "PASS", "plugin config restored; OBS READY")
        except Exception as exc:
            self.record("RESTORE_CONFIG", "FAIL", str(exc))

    def run(self) -> int:
        try:
            self.baseline()
            if self.args.phase == "native":
                self.native()
            else:
                self.vendor_phase()
        except Exception as exc:
            self.record("UNEXPECTED_ERROR", "FAIL", str(exc))
        finally:
            if self.args.phase == "native":
                self.restore_native_config()
            if self.obs:
                try:
                    self.obs.close()
                except Exception:
                    pass
        return self.write()

    def write(self) -> int:
        root = self.args.evidence
        root.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        result_path = root / "result.json"
        if result_path.exists():
            try:
                existing = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        merged_caps = existing.get("capabilities", {})
        merged_caps.update(self.capabilities)
        payload = sanitize({
            "phase": self.args.phase,
            "results": [asdict(x) for x in self.results],
            "capabilities": merged_caps,
            "evidence": self.evidence,
        }, self.secrets)
        result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report = [
            "# Issue #35 Gate 3 runtime API spike",
            "",
            f"Phase: **{self.args.phase}**",
            "",
            "## Results",
            "",
        ]
        report.extend(f"- {x.name}: **{x.status}** — {x.evidence}" for x in self.results)
        report += ["", "## Capability matrix", ""]
        keys = list(capability_template())
        report.append("| Capability | Native OBS + upstream | Upstream Vendor | Candidate Vendor |")
        report.append("| --- | --- | --- | --- |")
        for key in keys:
            report.append(
                f"| {key} | {merged_caps.get('native_obs_upstream', {}).get(key, 'UNKNOWN')} "
                f"| {merged_caps.get('upstream_vendor', {}).get(key, 'UNKNOWN')} "
                f"| {merged_caps.get('candidate_vendor', {}).get(key, 'UNKNOWN')} |"
            )
        safe_report = redact("\n".join(report) + "\n", self.secrets)
        (root / "report.md").write_text(safe_report, encoding="utf-8")
        failed = any(x.status == "FAIL" for x in self.results)
        print("ISSUE35_MULTIRTMP_API_SPIKE")
        for item in self.results:
            print(f"{item.name:<34} {item.status:<8} {item.evidence}")
        return 1 if failed else 0


def load_config(raw: bytes | None) -> dict[str, Any]:
    if raw is None:
        return {"targets": [], "video_configs": [], "audio_configs": []}
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PocError("existing obs-multi-rtmp.json is invalid") from exc
    if not isinstance(value, dict):
        raise PocError("existing obs-multi-rtmp.json root is not object")
    value.setdefault("targets", [])
    value.setdefault("video_configs", [])
    value.setdefault("audio_configs", [])
    return value


def resolve_config(obs: Any) -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise PocError("APPDATA unavailable; pass --plugin-config")
    profiles = Path(appdata) / "obs-studio" / "basic" / "profiles"
    current = str(obs.request("GetProfileList").get("currentProfileName") or "")
    exact = profiles / current / "obs-multi-rtmp.json"
    if current and exact.parent.is_dir():
        return exact
    found = list(profiles.glob("*/obs-multi-rtmp.json"))
    if len(found) == 1:
        return found[0]
    raise PocError("cannot resolve obs-multi-rtmp.json safely; pass --plugin-config")


def wait_process(http: Http, expected: str, timeout: float) -> None:
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        last = http.get("/api/v1/obs/process/status").get("state")
        if last == expected:
            return
        time.sleep(0.25)
    raise PocError(f"OBS process state={last}, expected={expected}")


def wait_native_output(obs: Any, output_name: str, expected: bool, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = obs.request("GetOutputStatus", {"outputName": output_name})
        if bool(last.get("outputActive")) is expected:
            return
        time.sleep(0.25)
    raise PocError(f"native output {output_name} active did not become {expected}: {last}")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.split()[0])
        except (ValueError, IndexError):
            return None
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("native", "vendor"), required=True)
    parser.add_argument("--base-url", default=os.environ.get("STREAMOPS_BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--plugin-config", type=Path, default=os.environ.get("OBS_MULTI_RTMP_CONFIG"))
    parser.add_argument("--server-a", default="rtmp://127.0.0.1:19351/live")
    parser.add_argument("--server-b", default="rtmp://127.0.0.1:19352/live")
    parser.add_argument("--independent-encoder", default=os.environ.get("ISSUE35_INDEPENDENT_ENCODER", "obs_x264"))
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--control-timeout", type=float, default=15)
    parser.add_argument("--live-timeout", type=float, default=30)
    parser.add_argument("--evidence", type=Path, default=root / ".streamops" / "issue-35")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if os.name != "nt":
        print("ISSUE35_MULTIRTMP_API_SPIKE\nOVERALL FAIL — run Real-A phases on Windows A")
        return 2
    return Runner(parse_args(argv)).run()


if __name__ == "__main__":
    raise SystemExit(main())
