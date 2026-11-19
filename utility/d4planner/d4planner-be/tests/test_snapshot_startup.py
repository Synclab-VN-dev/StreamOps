"""Real worker readiness with slow/failed identity checks and owned cleanup."""
import asyncio
import json
from pathlib import Path
import subprocess

import pytest

from d4planner.rulekit import LaunchSpecification, ProcessState, RuleKitProcessWrapper
from d4planner.rulekit.process import AsyncioProcessDriver

ROOT = Path(__file__).resolve().parents[4]
WORKER = ROOT / "utility/d4planner/d4planner-be/src/d4planner/rulekit/worker.js"
RULEKIT = ROOT / "utility/d4planner/d4planner-rulekit"


@pytest.mark.parametrize("scenario", ["slow", "query_failure", "deadline"])
def test_snapshot_identity_startup_budget_and_cleanup(tmp_path, scenario):
    # Instrument only this disposable worker composition, never production code.
    # On Windows, the successful path still executes the real native identity query.
    config = tmp_path / "config.json"
    data = tmp_path / "data"
    subprocess.run([
        "node", "-e",
        "const {trust}=require(process.argv[1]);require('node:fs').writeFileSync(process.argv[2],"
        "JSON.stringify({anchors:trust([]).registry.anchors,dataRoot:process.argv[3]}));",
        str(RULEKIT / "snapshot-management/tests/helpers.js"), str(config), str(data),
    ], check=True, timeout=10)
    composition = tmp_path / "composition.cjs"
    marker = tmp_path / "identity-entered"
    action = (
        "throw Object.assign(new Error('synthetic identity failure'),{code:'SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN'});"
        if scenario == "query_failure" else
        f"await new Promise(resolve=>setTimeout(resolve,{3200 if scenario == 'slow' else 30000}));return original();"
    )
    composition.write_text(
        f"const owner=require({json.dumps(str(RULEKIT / 'snapshot-management/src/process-owner.js'))});"
        "const original=owner.currentIdentity;owner.currentIdentity=async()=>{"
        f"require('node:fs').writeFileSync({json.dumps(str(marker))},'entered');{action}}};"
        f"module.exports=require({json.dumps(str(Path(__file__).parent / 'fixtures/snapshot-test-composition.js'))});",
        encoding="utf-8",
    )

    class RecordingDriver(AsyncioProcessDriver):
        child = None

        async def spawn(self, specification, **identity):
            self.child = await super().spawn(specification, **identity)
            return self.child

    async def run():
        driver = RecordingDriver()
        wrapper = RuleKitProcessWrapper(LaunchSpecification(
            executable="node", args=(str(WORKER),), working_directory=ROOT,
            environment_allow_list={"D4_RULEKIT_COMPOSITION_MODULE": str(composition),
                                    "TEST_SNAPSHOT_CONFIG": str(config)},
            # Success uses the same budget as production, including native lookup.
            **({"readiness_timeout": 3} if scenario == "deadline" else {}),
        ), driver)
        try:
            if scenario == "slow":
                await wrapper.start()
                assert wrapper.state == ProcessState.READY
                assert json.loads((data / ".manager.lock").read_text())["pid"] == driver.child.pid
            else:
                with pytest.raises(TimeoutError if scenario == "deadline" else RuntimeError):
                    await wrapper.start()
                assert wrapper.state == ProcessState.FAILED
                assert wrapper._child is None
            assert marker.read_text() == "entered"
        finally:
            await wrapper.stop()
        assert driver.child.process.returncode is not None
        assert wrapper._child is None
        assert wrapper._stderr_task is None and wrapper._exit_task is None
        assert not (data / ".manager.lock").exists()

    asyncio.run(run())
