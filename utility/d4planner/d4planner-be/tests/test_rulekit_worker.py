from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from d4planner.rulekit import (
    LaunchSpecification,
    ProcessState,
    RuleKitClient,
    RuleKitProcessWrapper,
    RuleKitRemoteError,
    RuleKitRuntimeService,
)


ROOT = Path(__file__).resolve().parents[4]
WORKER = ROOT / "utility/d4planner/d4planner-be/src/d4planner/rulekit/worker.js"
COMPOSITION = ROOT / "utility/d4planner/d4planner-be/tests/fixtures/rulekit-test-composition.js"


def run(coro):
    return asyncio.run(coro)


def build(*, equipment=None, delay_ms=None):
    value = {
        "class": "Rogue",
        "equipment": equipment or {},
        "skills": {},
        "paragon": {},
        "effects": {},
    }
    if delay_ms is not None:
        value["testDelayMs"] = delay_ms
    return value


def create_request(value=None):
    return {
        "contractVersion": "d4-rulekit-application/v1",
        "providerId": "test.synthetic",
        "providerVersion": "1.0.0",
        "buildSchemaVersion": "synthetic-build/v1",
        "build": build() if value is None else value,
    }


def specification(**environment):
    return LaunchSpecification(
        executable="node",
        args=(str(WORKER),),
        working_directory=ROOT,
        environment_allow_list={"D4_RULEKIT_COMPOSITION_MODULE": str(COMPOSITION), **environment},
        readiness_timeout=3,
        graceful_stop_timeout=2,
        kill_timeout=1,
        operation_timeout=1,
        max_pending=8,
        max_restarts=2,
    )


def test_ready_concurrent_start_and_graceful_owned_stop():
    async def scenario():
        wrapper = RuleKitProcessWrapper(specification())
        first, second = await asyncio.gather(wrapper.start(), wrapper.start())
        assert first is second
        assert wrapper.state is ProcessState.READY
        assert (await wrapper.inspect_health())["ready"] is True
        child = wrapper._child
        await wrapper.stop()
        assert wrapper.state is ProcessState.STOPPED
        assert child.process.returncode is not None

    run(scenario())


def test_ready_version_mismatch_fails_start_and_cleans_owned_child():
    async def scenario():
        code = (
            "console.log(JSON.stringify({type:'READY',protocolVersion:'wrong',"
            "applicationContractVersion:'d4-rulekit-application/v1',"
            "workerInstanceId:process.env.D4_RULEKIT_WORKER_INSTANCE_ID,"
            "workerGeneration:Number(process.env.D4_RULEKIT_WORKER_GENERATION),"
            "apis:[],health:{ready:true}}));setInterval(()=>{},1000)"
        )
        spec = LaunchSpecification(
            executable="node", args=("-e", code), working_directory=ROOT,
            readiness_timeout=1, graceful_stop_timeout=1, kill_timeout=1,
        )
        wrapper = RuleKitProcessWrapper(spec)
        with pytest.raises(RuntimeError, match="protocolVersion mismatch"):
            await wrapper.start()
        assert wrapper.state is ProcessState.FAILED
        assert wrapper._child is None

    run(scenario())


def test_all_eight_application_apis_and_complete_equipment_transitions():
    async def scenario():
        wrapper = RuleKitProcessWrapper(specification())
        client = await wrapper.start()
        try:
            providers = await client.list_providers()
            assert [(item["id"], item["version"]) for item in providers] == [("test.synthetic", "1.0.0")]
            session = await client.create_session(create_request())
            initial = await client.evaluate(session)
            assert initial["metrics"][0]["rawValue"] == 0
            change = [{"type": "equipment.replace", "slot": "HEAD", "item": {"id": "synthetic-helm"}}]
            preview = await client.preview_changes(session, {"expectedRevision": 0, "changes": change})
            assert preview["after"][0]["rawValue"] == 1
            committed = await client.commit_changes(session, {
                "expectedRevision": 0, "changes": change, "previewToken": preview["previewToken"]
            })
            assert committed["session"]["revision"] == 1
            replacement = [{"type": "equipment.replace", "slot": "HEAD", "item": {"id": "synthetic-helm-2"}}]
            preview = await client.preview_changes(session, {"expectedRevision": 1, "changes": replacement})
            committed = await client.commit_changes(session, {
                "expectedRevision": 1, "changes": replacement, "previewToken": preview["previewToken"]
            })
            assert committed["session"]["revision"] == 2
            removal = [{"type": "equipment.replace", "slot": "HEAD", "item": None}]
            preview = await client.preview_changes(session, {"expectedRevision": 2, "changes": removal})
            assert preview["after"][0]["rawValue"] == 0
            committed = await client.commit_changes(session, {
                "expectedRevision": 2, "changes": removal, "previewToken": preview["previewToken"]
            })
            assert committed["session"]["revision"] == 3
            assert (await client.get_session(session))["revision"] == 3
            reset = await client.reset_session(session, {"expectedRevision": 3})
            assert reset["revision"] == 4
            assert (await client.evaluate(session))["metrics"][0]["rawValue"] == 0
            await client.close_session(session)
        finally:
            await wrapper.stop()

    run(scenario())


def test_incomplete_build_rejected_and_capacity_is_bounded():
    async def scenario():
        wrapper = RuleKitProcessWrapper(specification(D4_RULEKIT_MAX_SESSIONS="1"))
        client = await wrapper.start()
        try:
            with pytest.raises(RuleKitRemoteError) as invalid:
                await client.create_session(create_request({}))
            assert invalid.value.code == "INVALID_INPUT"
            session = await client.create_session(create_request())
            with pytest.raises(RuleKitRemoteError) as capacity:
                await client.create_session(create_request())
            assert capacity.value.code == "QUOTA_EXCEEDED"
            await client.close_session(session)
        finally:
            await wrapper.stop()

    run(scenario())


def test_production_runtime_service_requires_pinned_absolute_resources(tmp_path):
    with pytest.raises(ValueError, match="executable"):
        RuleKitRuntimeService.from_environment({})
    node = tmp_path / "node"; node.write_text("")
    worker = tmp_path / "worker.js"; worker.write_text("")
    profile = tmp_path / "profile.json"; profile.write_text("{}")
    snapshot = tmp_path / "snapshot"; snapshot.mkdir()
    service = RuleKitRuntimeService.from_environment({
        "D4PLANNER_RULEKIT_EXECUTABLE": str(node.resolve()),
        "D4PLANNER_RULEKIT_WORKER": str(worker.resolve()),
        "D4PLANNER_RULEKIT_WORKING_DIR": str(tmp_path.resolve()),
        "D4_RULEKIT_PROFILE_JSON": str(profile.resolve()),
        "D4_RULEKIT_SNAPSHOT_ROOT": str(snapshot.resolve()),
    })
    assert service.wrapper.specification.executable == str(node.resolve())
    assert "D4_RULEKIT_COMPOSITION_MODULE" not in service.wrapper.specification.environment_allow_list


def test_operation_timeout_cancels_without_changing_session_lease_contract():
    async def scenario():
        wrapper = RuleKitProcessWrapper(specification())
        client = await wrapper.start()
        try:
            session = await client.create_session(create_request(build(delay_ms=250)))
            with pytest.raises(RuleKitRemoteError) as timeout:
                await client.call("evaluate", {"sessionId": session.session_id, "options": {}}, timeout=0.02)
            assert timeout.value.code == "TIMEOUT"
            assert client.pending_count == 0
        finally:
            await wrapper.stop()

    run(scenario())


def test_operation_deadline_bounds_hung_request_drain_cancel_and_pending_cleanup():
    class HungDrainWriter:
        def __init__(self):
            self.transport = self
            self.payloads = []
            self.closed = False

        def write(self, payload):
            self.payloads.append(payload)

        async def drain(self):
            await asyncio.Event().wait()

        def is_closing(self):
            return self.closed

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

        def abort(self):
            self.closed = True

    async def scenario():
        writer = HungDrainWriter()
        client = RuleKitClient(
            reader=asyncio.StreamReader(), writer=writer,
            worker_instance_id="hung-send", worker_generation=1,
            operation_timeout=0.05,
        )
        started = asyncio.get_running_loop().time()
        with pytest.raises(RuleKitRemoteError) as timeout:
            await client.call("listProviders", timeout=0.05)
        elapsed = asyncio.get_running_loop().time() - started
        assert timeout.value.code == "TIMEOUT"
        assert elapsed < 0.15
        assert client.pending_count == 0
        assert len(writer.payloads) >= 1
        await client.close()

    run(scenario())


def test_sessions_are_isolated_and_idle_expiry_is_typed_over_ipc():
    async def scenario():
        wrapper = RuleKitProcessWrapper(specification(D4_RULEKIT_SESSION_TTL_MS="40"))
        client = await wrapper.start()
        try:
            empty, equipped = await asyncio.gather(
                client.create_session(create_request(build())),
                client.create_session(create_request(build(equipment={"HEAD": {"id": "helm"}}))),
            )
            results = await asyncio.gather(client.evaluate(empty), client.evaluate(equipped))
            assert [result["metrics"][0]["rawValue"] for result in results] == [0, 1]
            await asyncio.sleep(0.08)
            with pytest.raises(RuleKitRemoteError) as expired:
                await client.get_session(empty)
            # The background reaper may already have completed cleanup; both
            # states fail closed and never revive the expired session.
            assert expired.value.code in {"SESSION_EXPIRED", "SESSION_NOT_FOUND"}
        finally:
            await wrapper.stop()

    run(scenario())


def test_restart_invalidates_session_and_old_generation_cannot_be_reused():
    async def scenario():
        wrapper = RuleKitProcessWrapper(specification())
        old_client = await wrapper.start()
        session = await old_client.create_session(create_request())
        old_generation = wrapper.generation
        new_client = await wrapper.restart()
        try:
            assert wrapper.generation == old_generation + 1
            with pytest.raises(RuleKitRemoteError) as stale:
                await new_client.evaluate(session)
            assert stale.value.code == "STALE_WORKER_GENERATION"
            replacement = await new_client.create_session(create_request())
            assert (await new_client.evaluate(replacement))["revision"] == 0
        finally:
            await wrapper.stop()

    run(scenario())


def test_crash_is_detected_and_restart_budget_is_bounded():
    async def scenario():
        wrapper = RuleKitProcessWrapper(specification())
        await wrapper.start()
        child = wrapper._child
        child.process.kill()
        await asyncio.wait_for(child.process.wait(), 2)
        await asyncio.sleep(0)
        assert wrapper.state is ProcessState.FAILED
        await wrapper.restart()
        await wrapper.restart()
        with pytest.raises(RuntimeError, match="budget exhausted"):
            await wrapper.restart()
        await wrapper.stop()

    run(scenario())


def test_parent_pipe_eof_stops_worker_without_orphan():
    async def scenario():
        process = await asyncio.create_subprocess_exec(
            "node", str(WORKER), cwd=ROOT,
            env={
                **os.environ,
                "D4_RULEKIT_COMPOSITION_MODULE": str(COMPOSITION),
                "D4_RULEKIT_WORKER_INSTANCE_ID": "parent-eof-test",
                "D4_RULEKIT_WORKER_GENERATION": "1",
            },
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        ready = json.loads(await asyncio.wait_for(process.stdout.readline(), 2))
        assert ready["type"] == "READY"
        process.stdin.close()
        await process.stdin.wait_closed()
        assert await asyncio.wait_for(process.wait(), 2) == 0
        assert await process.stdout.read() == b""
        assert await process.stderr.read() == b""

    run(scenario())


def test_client_close_aborts_a_writer_that_never_reports_closed_within_budget():
    class NeverClosingWriter:
        def __init__(self):
            self.transport = self
            self.close_calls = 0
            self.abort_calls = 0

        def is_closing(self):
            return self.close_calls > 0

        def close(self):
            self.close_calls += 1

        async def wait_closed(self):
            await asyncio.Event().wait()

        def abort(self):
            self.abort_calls += 1

    async def scenario():
        writer = NeverClosingWriter()
        client = RuleKitClient(
            reader=asyncio.StreamReader(), writer=writer,
            worker_instance_id="hung-writer", worker_generation=1,
            operation_timeout=0.04,
        )
        started = asyncio.get_running_loop().time()
        await client.close()
        elapsed = asyncio.get_running_loop().time() - started
        assert elapsed < 0.2
        assert writer.close_calls == 1
        assert writer.abort_calls == 1
        await client.close()
        assert writer.abort_calls == 1

    run(scenario())


def test_public_protocol_surface_has_only_owner_approved_application_apis():
    from d4planner.rulekit.protocol import APPROVED_METHODS

    assert APPROVED_METHODS == {
        "listProviders", "createSession", "evaluate", "previewChanges",
        "commitChanges", "resetSession", "getSession", "closeSession",
    }
    sources = WORKER.read_text(encoding="utf-8") + (ROOT / "utility/d4planner/d4planner-rulekit/application/src/runtime/production-composition.js").read_text(encoding="utf-8")
    assert "Torment" not in sources
    assert "D4_RULEKIT_COMPOSITION_MODULE" not in (ROOT / "utility/d4planner/d4planner-rulekit/application/src/runtime/production-composition.js").read_text(encoding="utf-8")


@pytest.mark.parametrize('exit_before_ready', [False, True])
def test_startup_stderr_backpressure_never_blocks_ready_or_exit(exit_before_ready):
    """Real Node pipe test, including long lines; stderr is never forwarded."""
    from dataclasses import replace
    async def scenario():
        continuation = 'process.exit(23)' if exit_before_ready else f'require({json.dumps(str(COMPOSITION))}).createComposition(process.env).then(require({json.dumps(str(WORKER))}).main)'
        code = "process.stderr.write('SYNTHETIC_PRIVATE_DIAGNOSTIC'.repeat(100000),()=>{" + continuation + "});"
        wrapper = RuleKitProcessWrapper(replace(specification(), args=('-e', code)))
        try:
            if exit_before_ready:
                with pytest.raises(RuntimeError, match='exited before READY'):
                    await wrapper.start()
                assert wrapper._child is None
                assert wrapper._stderr_task is None
            else:
                client = await wrapper.start()
                assert (await client.list_providers())[0]['id'] == 'test.synthetic'
        finally:
            await wrapper.stop()
        assert wrapper._child is None and wrapper._stderr_task is None
    run(scenario())
