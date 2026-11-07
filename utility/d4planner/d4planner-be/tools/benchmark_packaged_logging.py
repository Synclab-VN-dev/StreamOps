"""Paired LOG-09 measurement using the installed Launcher and native HUD runner."""
from __future__ import annotations
import argparse
import platform
from pathlib import Path
import sys
import time

from logging_acceptance import comparison, native_sample, percentiles, read_json, write_json
from windows_setup_e2e import sha


def benchmark(args):
    if sys.platform != "win32":
        raise RuntimeError("interactive isolated Windows VM required")
    if args.runs < 2 or args.samples < 1:
        raise ValueError("at least two pairs and one operation per run required")
    root = args.install_root.resolve()
    active = read_json(root / "active.json")
    payload = root / active["payload"]
    manifest = read_json(payload / "release-manifest.json")
    assert manifest["sourceHead"] == args.source_head, "exact installed source required"
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"sourceHead": args.source_head, "setupSha256": sha(args.setup), "os": platform.platform(),
              "classification": "WINDOWS_NATIVE_PACKAGED_RECORDED_SYNTHETIC_INPUT_NO_SNAPSHOT",
              "baseline": "Same installed bytes; fresh DataDir/logs is a file, exercising existing fail-open initialization",
              "sla": "NO_NEW_SLA", "runs": [], "status": "RUNNING",
              "limits": ["Baseline includes one failed directory initialization; it is not a pre-S8 build",
                         "BE and Rule Kit READY timestamps are INFO-only diagnostics, not paired overhead estimates",
                         "JS timestamps have millisecond resolution; render uses existing double animation frame acknowledgment",
                         "No live game or production snapshot; worker process READY does not mean calculation READY",
                         "Alternating order, fresh DataDir per run; first pair retained as warmup and excluded from quantiles",
                         "CPU/IO are cumulative live-child counters; RAM is one end-of-workload snapshot, not peak RSS"]}
    started = time.perf_counter()
    try:
        for pair in range(args.runs + 1):
            for mode in (("disabled", "INFO") if pair % 2 == 0 else ("INFO", "disabled")):
                name = f"pair-{pair}-{mode}"
                result = native_sample(root, payload, args.output / (name + "-data"), args.output / name,
                                       mode=mode, samples=args.samples)
                result.update(pair=pair, warmup=pair == 0)
                report["runs"].append(result)
                write_json(args.output / "benchmark.json", report)
        arms = {mode: [r for r in report["runs"] if r["mode"] == mode and not r["warmup"]] for mode in ("disabled", "INFO")}
        report["startupToRenderMs"] = comparison(*[[r["startupToRenderMs"] for r in arms[mode]] for mode in arms])
        report["targetActivationMs"] = comparison(*[[r["targetActivationMs"] for r in arms[mode]] for mode in arms])
        report["stages"] = {stage: comparison(*[[v for r in arms[mode] for v in r["stages"][stage]["samples"]] for mode in arms])
                            for stage in arms["INFO"][0]["stages"]}
        report["INFOReadyDiagnostics"] = {name: percentiles([r[name] for r in arms["INFO"]]) for name in ("beReadyMs", "rulekitReadyMs")}
        report["lossMarkers"] = [entry for r in arms["INFO"] for f in r["logging"]["files"].values() for entry in f["lossMarkers"]]
        assert not report["lossMarkers"], "diagnostic loss under the measured workload requires investigation"
        report["status"] = "MEASURED"
    except Exception as error:
        report.update(status="FAIL", error=repr(error))
        raise
    finally:
        report["durationSeconds"] = time.perf_counter() - started
        write_json(args.output / "benchmark.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("install-root", "setup", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--samples", type=int, default=20)
    benchmark(parser.parse_args())


if __name__ == "__main__":
    main()
