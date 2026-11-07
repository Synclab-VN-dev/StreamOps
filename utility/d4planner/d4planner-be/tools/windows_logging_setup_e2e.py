"""LOG-10 final Setup cycle, confined to a fresh sandbox and UAT identity.

Reuses the production installer engine's durable checkpoints and native E2E
observations. No production registry fixtures, global runtime, or snapshot.
Run with a private harness Python outside InstallRoot in an isolated VM.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback

from logging_acceptance import log_evidence, native_sample, read_json, write_json
from windows_setup_e2e import sha, owned_tree
from windows_installer_review_e2e import alive


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in root.rglob("*") if p.is_file()}


def preserved(root, before):
    actual = inventory(root)
    assert all(actual.get(name) == digest for name, digest in before.items()), "user file missing or changed"
    return {"files": len(before), "unchanged": True}


def seed_upgrade_data(source, destination):
    """Seed user inputs, letting the old runtime create its own compatible HUD DB."""
    for name in ("logs", "state", "targets", "settings.json", "user-owned.bin", "launcher.json", "recorded-producer.sqlite3"):
        old, new = source / name, destination / name
        if old.is_dir():
            shutil.copytree(old, new, dirs_exist_ok=True, ignore=shutil.ignore_patterns("hud.sqlite3*"))
        else:
            shutil.copyfile(old, new)
    config = read_json(destination / "launcher.json")
    config["equipmentRepository"]["path"] = str(destination / "recorded-producer.sqlite3")
    write_json(destination / "launcher.json", config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sandbox", "setup-old", "setup-new", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--benchmark-runs", type=int, default=10)
    parser.add_argument("--benchmark-samples", type=int, default=20)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise RuntimeError("WINDOWS_REQUIRED")
    import winreg
    sandbox, output = args.sandbox.resolve(), args.output.resolve()
    sandbox.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("D4PLANNER_", "D4_RULEKIT_", "D4_LOG_", "D4_HUD_"))}
    env["PATH"] = os.pathsep.join([os.environ["SYSTEMROOT"] + r"\System32", os.environ["SYSTEMROOT"] + r"\System32\WindowsPowerShell\v1.0"])
    report = {"sourceHead": args.source_head, "os": platform.platform(), "harnessPython": sys.version,
              "artifacts": {"oldSetup": sha(args.setup_old), "finalSetup": sha(args.setup_new)},
              "classification": "WINDOWS_NATIVE_FINAL_SETUP_SYNTHETIC_INPUT", "cases": [], "commands": []}
    root = sandbox / "fresh-app"; data = sandbox / "fresh-data"; launch = None; trees = []
    keys = [r"Software\Synclab\D4Planner-UAT", r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4PlannerUAT"]
    def registry(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                rows = {}; i = 0
                while True:
                    try: name, value, kind = winreg.EnumValue(key, i)
                    except OSError: return rows
                    rows[name] = [value, kind]; i += 1
        except FileNotFoundError:
            return None
    # Read-only production registration comparison. Never create/delete it.
    production_keys = [r"Software\Synclab\D4Planner", r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4Planner"]
    production_before = {k: registry(k) for k in production_keys}
    assert all(registry(k) is None for k in keys), "existing UAT registration must not be stolen"
    def save(): write_json(output / "setup-acceptance.json", report)
    def call(command, *, check=True, timeout=240):
        tick = time.perf_counter()
        result = subprocess.run(command if isinstance(command, str) else list(map(str, command)), env=env,
                                capture_output=True, text=True, timeout=timeout)
        report["commands"].append({"command": command if isinstance(command, str) else list(map(str, command)),
                                   "exitCode": result.returncode, "durationSeconds": time.perf_counter() - tick})
        with (output / "commands.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{command}\nexit={result.returncode}\n{result.stdout}\n{result.stderr}\n")
        save()
        if check: assert result.returncode == 0, (result.returncode, result.stderr[-500:])
        return result
    def case(identifier, expected, action):
        tick = time.perf_counter()
        try:
            actual = action(); status = "PASS"
        except Exception as error:
            actual = repr(error); status = "FAIL"
            (output / (identifier + "-failure.txt")).write_text(traceback.format_exc(), encoding="utf-8")
        report["cases"].append({"id": identifier, "expected": expected, "actual": actual,
                                 "status": status, "durationSeconds": time.perf_counter() - tick})
        save(); print(json.dumps(report["cases"][-1]), flush=True)
        return status == "PASS"
    def state(): return read_json(root / "active.json")
    def payload(): return root / state()["payload"]
    def setup(path):
        call(f'"{path}" /S /ISOLATED=1 /DATADIR="{data}" /INSTALLROOT="{root}"')
        assert Path(registry(keys[1])["InstallLocation"][0]) == root
        return state()
    def uninstall(before):
        # Contract: delete manifest-owned payloads, preserve unrecognized files.
        # Runtime-created .pyc files are not in the release manifest; requiring
        # versions/ to disappear would silently change that preservation policy.
        declared = set()
        for manifest_path in root.glob("versions/*/release-manifest.json"):
            manifest = read_json(manifest_path)
            assert manifest["applicationId"] == state()["applicationId"]
            declared.add(manifest_path)
            declared.update(manifest_path.parent / entry["path"] for entry in manifest["files"])
        assert declared, "installed manifests required before uninstall"
        unowned = {p.relative_to(root).as_posix(): sha(p) for p in (root / "versions").rglob("*")
                   if p.is_file() and p not in declared}
        write_json(output / (root.name + "-unowned-files.json"), unowned)
        call([root / "Uninstall.exe", "/S"])
        deadline = time.monotonic() + 90
        while (root / "Uninstall.exe").exists() and time.monotonic() < deadline: time.sleep(.1)
        assert not (root / "D4Planner.exe").exists() and not (root / "Uninstall.exe").exists()
        assert not (root / "active.json").exists() and not (root / "maintenance").exists()
        assert not any(p.exists() for p in declared), "manifest-owned file remained"
        preserved(root, unowned)
        assert all(registry(k) is None for k in keys)
        return {"userData": preserved(data, before), "manifestOwnedFilesRemoved": len(declared),
                "unrecognizedFilesPreserved": len(unowned)}
    def stop():
        nonlocal launch
        if launch is not None:
            if launch.poll() is None: call([root / "D4Planner.exe", "--stop"])
            code = launch.wait(timeout=25)
            launch = None
            assert code == 0, f"launcher exited {code}"
    def clean_runtime():
        for tool in ("python.exe", "node.exe", "rustc.exe"):
            assert call(["where.exe", tool], check=False).returncode != 0, "global toolchain on PATH"
        # Inventory registered global development runtimes too, not merely PATH.
        result = call(["powershell.exe", "-NoProfile", "-Command",
            "@(Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -match '^(Python |Node.js|Rust )'} | Select-Object DisplayName,DisplayVersion) | ConvertTo-Json -Compress"])
        assert not result.stdout.strip() or json.loads(result.stdout) == [], "global dev runtime registration present"
        return {"globalToolchains": [], "path": env["PATH"]}
    try:
        if not case("ENV", "No global Python/Node/Rust; private harness outside installation", clean_runtime): return 1
        def fresh():
            value = setup(args.setup_new)
            manifest = read_json(payload() / "release-manifest.json")
            assert manifest["sourceHead"] == args.source_head
            return {"version": value["version"], "sourceHead": manifest["sourceHead"], "setupSha256": sha(args.setup_new)}
        if not case("FRESH", "Final exact-HEAD Setup installs under UAT identity", fresh): return 1
        def logging():
            result = native_sample(root, payload(), data, output / "fresh-native", samples=3)
            current = read_json(output / "fresh-native/db-initial.json")
            assert current["payload"]["health"]["ruleKit"] == "UNAVAILABLE", "no-snapshot must not fake calculation READY"
            assert not list((data / "rulekit").rglob("snapshot-manifest.json"))
            return {"logging": result["logging"], "workerProcess": "READY", "calculation": "UNAVAILABLE", "ownedProcessesAfter": 0}
        if not case("LOGGING", "Native Launcher/FE/BE/worker, same-run three logs, no-snapshot honest", logging): return 1
        def performance():
            from benchmark_packaged_logging import benchmark
            result = benchmark(argparse.Namespace(install_root=root, setup=args.setup_new, source_head=args.source_head,
                output=output / "benchmark", runs=args.benchmark_runs, samples=args.benchmark_samples))
            return {"status": result["status"], "report": "benchmark/benchmark.json"}
        case("LOG-09-MEASURE", "Paired same-build startup/native render/update overhead measured", performance)
        (data / "settings.json").write_text('{"userOwned":"preserve"}')
        (data / "user-owned.bin").write_bytes(b"LOG-10 preservation canary")
        with sqlite3.connect(data / "state/user.sqlite3") as db:
            db.execute("CREATE TABLE user_data(value TEXT)")
            db.execute("INSERT INTO user_data VALUES ('LOG-10 user database canary')")
        before = inventory(data)
        write_json(output / "fresh-data-inventory.json", before)
        if not case("FRESH-UNINSTALL", "Uninstall removes application, preserves every user/log byte", lambda: uninstall(before)): return 1
        old_data = data
        root = sandbox / "upgrade-app"; data = sandbox / "upgrade-data"
        if not case("OLD-INSTALL", "Compatible previous Setup installs in separate fresh UAT root", lambda: setup(args.setup_old)): return 1
        # Closed genuine logs and user state from the final Setup are user-owned
        # upgrade inputs; retain hashes. Do not copy transient locks/control files.
        seed_upgrade_data(old_data, data)
        baseline = inventory(data)
        write_json(output / "upgrade-data-inventory.json", baseline)
        def upgrading():
            nonlocal launch, baseline
            previous = state()
            launch = subprocess.Popen([str(root / "D4Planner.exe"), "--launch"], env=env)
            deadline = time.monotonic() + 60
            tree = []
            while time.monotonic() < deadline:
                tree = owned_tree(launch.pid)
                if any(r["name"].lower() == "node.exe" for r in tree): break
                assert launch.poll() is None, f"old launcher exited {launch.returncode}"
                time.sleep(.1)
            assert any(r["name"].lower() == "node.exe" for r in tree), "old runtime worker did not start"
            assert (data / "state/hud.sqlite3").is_file(), "old runtime must create its own HUD database"
            trees.extend(tree)
            # Runtime-owned SQLite may legitimately change during launch. Verify
            # immutable user files/logs separately and logical DB state below.
            baseline = {k: v for k, v in baseline.items() if not k.startswith("state/hud.sqlite3")}
            value = setup(args.setup_new)
            assert value["version"] != previous["version"], "distinct compatible versions required"
            stop()
            assert not any(alive(r["pid"]) for r in tree)
            assert read_json(payload() / "release-manifest.json")["sourceHead"] == args.source_head
            preserved(data, baseline)
            with sqlite3.connect(data / "state/user.sqlite3") as db:
                assert db.execute("SELECT value FROM user_data").fetchall() == [("LOG-10 user database canary",)]
            return {"beforeVersion": previous["version"], "afterVersion": value["version"], "ownedProcessesAfter": 0,
                    "preserved": len(baseline), "databasePresent": (data / "state/hud.sqlite3").is_file()}
        if not case("UPGRADE-RUNNING", "Old running application upgrades to exact final Setup; logs/state retained", upgrading): return 1
        def upgraded_runtime():
            nonlocal launch
            import production_e2e as e2e
            old_runs = {p.name for p in (data / "logs").iterdir() if p.is_dir()}
            render = output / "upgraded-render.json"
            runtime_env = dict(env, D4_HUD_PIPELINE_REPORT=str(render), D4_HUD_PIPELINE_CONTINUOUS="1")
            launch = subprocess.Popen([str(root / "D4Planner.exe"), "--launch"], env=runtime_env)
            def observed():
                assert launch.poll() is None, "upgraded launcher exited"
                try: return read_json(render)
                except (ValueError, OSError): return None
            ui = e2e._wait_for(observed, 90, "upgraded user configuration renders")
            tree = owned_tree(launch.pid); trees.extend(tree)
            stop()
            assert not any(alive(row["pid"]) for row in tree)
            selected = read_json(data / "state/selected-target.json")
            assert ui["targetId"] == selected["targetId"] == "synthetic-target-b"
            db = e2e._sqlite_evidence(data / "state/hud.sqlite3", output / "upgraded-db.sqlite3", output / "upgraded-db.json")
            e2e._assert_ui_matches_db(ui, db)
            preserved(data, baseline)
            new_runs = {p.name for p in (data / "logs").iterdir() if p.is_dir()} - old_runs
            assert len(new_runs) == 1
            return {"logging": log_evidence(data, new_runs.pop()), "configuredTarget": ui["targetId"],
                    "configurationPreserved": True, "userDatabasePreserved": True, "ownedProcessesAfter": 0}
        def recovery():
            previous = state(); launcher_hash = sha(root / "D4Planner.exe")
            results = []
            for phase in ("JOURNALED", "LAUNCHER_REPLACED", "ACTIVATED"):
                script = (f"import os,sys;from pathlib import Path;sys.path.insert(0,{str(payload() / 'tools')!r});import windows_install;"
                          f"windows_install.rollback(Path({str(root)!r}),checkpoint=lambda p:os._exit(73) if p=={phase!r} else None)")
                failed = call([sys.executable, "-c", script], check=False)
                assert failed.returncode == 73
                assert (root / "upgrade-journal.json").is_file()
                # Active payload may now point to old version. Use the final
                # engine retained in previous's immutable version directory.
                engine = root / previous["payload"] / "tools/windows_install.py"
                call([sys.executable, engine, "recover", "--root", root, "--report", output / f"recover-{phase}.json"])
                assert state() == previous and sha(root / "D4Planner.exe") == launcher_hash
                assert not (root / "upgrade-journal.json").exists()
                preserved(data, baseline)
                results.append({"checkpoint": phase, "injectedExitCode": 73, "restoredFinalVersion": True})
            call([root / "D4Planner.exe", "--runtime-health", "--health-report", output / "recovered-health.json"], timeout=90)
            assert read_json(output / "recovered-health.json")["runtimeReady"] is True
            return results
        case("RECOVERY", "Interrupted activation during rollback restores final launcher/state and passes runtime health", recovery)
        # Exercise compatible activation before the final app migrates its HUD
        # database. A downgrade after migration must be rejected by the engine.
        case("UPGRADED-RUNTIME", "Final installed app reopens actual preserved config/Target/DB and adds a same-ID log set", upgraded_runtime)
        final_inventory = inventory(data)
        write_json(output / "pre-uninstall-inventory.json", final_inventory)
        case("UPGRADE-UNINSTALL", "Final Setup uninstalls and retains all current user/log/DB bytes", lambda: uninstall(final_inventory))
    finally:
        try:
            stop_error = None
            try: stop()
            except Exception as error: stop_error = repr(error)
            # Even failed scenarios leave the dedicated installation unregistered.
            if (root / "Uninstall.exe").exists():
                case("FAILURE-CLEANUP", "Failed scenario uninstalls without deleting user data", lambda: uninstall(inventory(data)))
            assert all(registry(k) is None for k in keys)
            assert all(registry(k) == production_before[k] for k in production_keys)
            assert not any(alive(row["pid"]) for row in trees)
            # Also inspect executable ownership, including descendants created
            # after the captured process trees (and their listeners).
            escaped = str(sandbox).replace("'", "''") + "\\"
            checked = call(["powershell.exe", "-NoProfile", "-Command",
                f"$owned=@(Get-CimInstance Win32_Process | Where-Object {{$_.ExecutablePath -and $_.ExecutablePath.StartsWith('{escaped}')}});"
                "$listeners=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.OwningProcess -in $owned.ProcessId});"
                "@{processes=@($owned|Select-Object ProcessId,Name);listeners=@($listeners|Select-Object LocalPort,OwningProcess)}|ConvertTo-Json -Compress"])
            cleanup = json.loads(checked.stdout)
            assert not cleanup["processes"] and not cleanup["listeners"], "owned process/listener leak"
            assert stop_error is None, stop_error
            report["cleanup"] = {"uatRegistrationRemoved": True, "productionRegistrationUnchanged": True,
                                 "ownedProcessesAfter": 0, "ownedListenersAfter": 0}
        except Exception as error:
            report["cleanup"] = {"status": "FAIL", "error": repr(error)}
        report["status"] = "PASS" if report["cases"] and all(c["status"] == "PASS" for c in report["cases"]) and report.get("cleanup", {}).get("ownedProcessesAfter") == 0 else "FAIL"
        save()
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
