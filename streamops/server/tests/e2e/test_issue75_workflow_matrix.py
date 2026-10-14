"""FE #75 Playwright matrix over BE v2 contract-shaped WS simulation.

These tests prove browser/UI flow and safety only. A simulated transaction is
NOT evidence of real installer journal, SHA, rollback or vendor verification.
"""
from __future__ import annotations

import json
from playwright.sync_api import Page, expect
from .conftest import BrowserTestServer
from .test_issue75_plugin_manager import MockPluginWebSocket

class ScenarioWS(MockPluginWebSocket):
    def __init__(self, page: Page, *, plugin_state="NOT_INSTALLED",
                 obs_state="STOPPED", catalog=True, registry=True,
                 streaming=False, recording=False, rollback=False,
                 installed_version=None, release_version="2.0"):
        self.registry=registry
        self.has_catalog=catalog
        self.streaming=streaming
        self.recording=recording
        self.rollback=rollback
        self.installed_version=installed_version
        self.release_version=release_version
        self.revision=10
        self.read_error_once=False
        self.fail_operation=None
        self.auto_rollback_failure=False
        self.status_operation={"state":"IDLE","operation_id":None}
        self.obs_sockets=[]
        self.install_requires_restart=False
        self.already_adopted=False
        self.rollback_alias_override=None
        self.rollback_missing_proof=False
        super().__init__(page, plugin_state=plugin_state, obs_state=obs_state)

    def status(self):
        current=super().status()
        current.update({
            "installed_version": self.installed_version,
            "revision":self.revision,
            "restart_required": self.plugin_state == "RESTART_REQUIRED",
            "rollback":{"available":self.rollback,"reason":None if self.rollback else "baseline_unavailable"},
            "rollback_available":self.rollback,
            "operation":self.status_operation,
            "last_verification":None,
        })
        if self.rollback_alias_override is not None:
            current['rollback_available']=self.rollback_alias_override
        if self.rollback_missing_proof:
            current.pop('rollback',None)
        return current

    def approved_release(self):
        return {"plugin_id":"obs-multi-rtmp","display_name":"Multiple RTMP Outputs",
                "available_version":self.release_version,
                "installed_version":self.installed_version,
                "installable":True,"compatibility":"compatible","reason":None,
                "source_commit":"a"*40,
                "release_ref":"obs-multi-rtmp/v"+self.release_version}

    def plugin_socket(self,ws):
        self.sockets.append(ws)

        def handle(raw):
            request=json.loads(raw);self.calls.append(request)
            op=request["operation"]; data=None
            if op == "obs_plugin.inventory":
                if self.read_error_once:
                    self.read_error_once=False
                    ws.send(json.dumps({"type":"response","request_id":request["request_id"],
                        "ok":False,"error":{"code":"plugin_status_failed","message":"Backend unavailable"}}))
                    return
                data={"plugins":[self.status()] if self.registry else []}
            elif op == "obs_plugin.available":
                data={"plugins":[self.approved_release()] if self.has_catalog else [],
                      "source_state":"READY" if self.has_catalog else "EMPTY"}
            elif op == "obs_plugin.subscribe":
                data={"plugin_id":request["payload"]["plugin_id"],
                      "subscribed":True,"revision":self.revision}
            elif op == "obs_plugin.operation_status":
                data={"plugin_id":request["payload"]["plugin_id"],
                      "revision":self.revision,"operation":self.status_operation,
                      "plugin_state":self.plugin_state,
                      "recovery_required":self.plugin_state=="RECOVERY_REQUIRED",
                      "rollback":{"available":self.rollback}}
            elif op in {"obs_plugin.adopt","obs_plugin.install","obs_plugin.update",
                        "obs_plugin.verify","obs_plugin.rollback"}:
                if request["payload"] != {"plugin_id":"obs-multi-rtmp"}:
                    raise AssertionError("Mutation must never include paths/URLs/binaries")
                if self.fail_operation is not None:
                    code=self.fail_operation
                    self.fail_operation=None
                    if code == "plugin_verify_failed":
                        self.plugin_state=(
                            "RECOVERY_REQUIRED" if self.auto_rollback_failure
                            else "VERIFY_FAILED"
                        )
                        self.revision+=1
                        if self.auto_rollback_failure:
                            # The backend attempted its own rollback while
                            # servicing Verify and failed. FE did not call it.
                            self.status_operation={
                                "state":"FAILED","operation":"verify",
                                "operation_id":"verify-auto-rollback-failed",
                                "error_code":"plugin_verify_failed",
                            }
                    elif code in {"plugin_recovery_required","plugin_rollback_failed"}:
                        self.plugin_state="RECOVERY_REQUIRED"
                        self.revision+=1
                    ws.send(json.dumps({"type":"response","request_id":request["request_id"],
                       "ok":False,"error":{"code":code,"message":"Backend rejected operation"}}))
                    self.push_changed()
                    return
                old_version=self.installed_version
                operation=op.split(".")[-1]
                if operation == "adopt":
                    self.plugin_state="LEGACY_ADOPTED"
                elif operation in {"install","update"}:
                    self.plugin_state="RESTART_REQUIRED" if self.install_requires_restart else "INSTALLED"
                    self.installed_version=self.release_version
                elif operation == "verify":
                    self.plugin_state="VERIFIED"
                elif operation == "rollback":
                    self.plugin_state="INSTALLED"
                    self.installed_version="1.0"
                    self.rollback=False
                self.revision+=1
                self.status_operation={"state":"SUCCEEDED","operation":operation,
                                       "operation_id":"scenario-"+str(self.revision)}
                data={**self.status(),"operation":operation,
                      "result":("already_adopted" if self.already_adopted else "adopted")
                          if operation=="adopt" else "completed",
                      "previous_version":old_version}
            else:
                raise AssertionError("Unexpected FE request "+op)
            ws.send(json.dumps({"type":"response","request_id":request["request_id"],
                                "ok":True,"data":data}))
            if op.startswith("obs_plugin.") and op.split(".")[-1] in {
                "adopt","install","update","verify","rollback"
            }:
                self.push_changed()
        ws.on_message(handle)

    def obs_socket(self,ws):
        self.obs_sockets.append(ws)
        def snapshot():
            ws.send(json.dumps({"type":"event","event":"obs.snapshot","data":{
                "runtime":{"state":self.obs_state,
                  "output":{"streaming":self.streaming,"recording":self.recording},
                  "websocket":{"connected":self.obs_state=="READY"}}}}))
        snapshot()

        def handle(raw):
            req=json.loads(raw);self.calls.append(req)
            # The existing OBS dashboard performs safe read-only queries on
            # page load. The test fixture must serve their documented schemas;
            # rejecting those reads makes unrelated Dashboard initialization fail.
            reads = {
                "source_catalog.list": {"sources": []},
                "scene_profile_templates.list": {"templates": []},
                "scene_profiles.list": {"profiles": []},
                "inventory.get": {"options": {}},
            }
            if req["operation"] in reads:
                assert req.get("payload", {}) == {}, "OBS read may not mutate resources"
                ws.send(json.dumps({"type":"response","request_id":req["request_id"],
                                    "ok":True,"data":reads[req["operation"]]}))
                return
            if req["operation"] != "obs.lifecycle.restart":
                raise AssertionError("No background OBS mutation is permitted")
            self.obs_state="READY"
            if self.plugin_state=="RESTART_REQUIRED":
                self.plugin_state="INSTALLED"
                self.revision+=1
            ws.send(json.dumps({"type":"response","request_id":req["request_id"],
                                "ok":True,"data":{"state":"READY"}}))
            snapshot()
            self.push_changed()
        ws.on_message(handle)

    def operator_starts_obs(self):
        """Model a *separate* operator action; FE must never auto-start OBS."""
        self.obs_state="READY"
        for ws in self.obs_sockets:
            ws.send(json.dumps({"type":"event","event":"obs.snapshot","data":{
                "runtime":{"state":"READY",
                  "output":{"streaming":False,"recording":False},
                  "websocket":{"connected":True}}}}))

    def push_changed(self):
        for ws in self.sockets:
            ws.send(json.dumps({"type":"event","event":"obs_plugin.changed","data":{
                "plugin_id":"obs-multi-rtmp","revision":self.revision,
                "resources":["status","operation"]}}))

    def mutations(self,op=None):
        return [r for r in self.calls
                if r["operation"] in {"obs_plugin.adopt","obs_plugin.install",
                    "obs_plugin.update","obs_plugin.verify","obs_plugin.rollback",
                    "obs.lifecycle.restart"}
                and (op is None or r["operation"]==op)]


def launch(page:Page,server:BrowserTestServer,scenario:ScenarioWS):
    page.goto(server.base_url+"/obs/plugins")
    expect(page.locator("#plugin-managed-count")).to_have_text("1" if scenario.registry else "0", timeout=15000)
    if scenario.registry:
        expect(page.locator(".plugin-card")).to_have_count(1)
        expect(page.locator(".plugin-card-header")).to_have_attribute("aria-expanded","true")


def act(page:Page,label:str):
    page.get_by_role("button",name=label,exact=True).click()
    expect(page.locator("#plugin-confirm-dialog")).to_be_visible()


def confirm(page:Page):
    page.get_by_role("button",name="Confirm",exact=True).click()
    expect(page.locator("#plugin-confirm-dialog")).not_to_be_visible()


def test_issue75_empty_registry_never_invents_a_plugin(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,registry=False)
    launch(page,live_server,fake)
    expect(page.locator(".plugin-card")).to_have_count(0)
    expect(page.locator("#plugin-list")).to_contain_text("No plugins")
    assert fake.mutations()==[]
    assert not [r for r in fake.calls if r["operation"]=="obs_plugin.subscribe"]


def test_issue75_inventory_error_then_explicit_refresh_recovers(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page)
    fake.read_error_once=True
    page.goto(live_server.base_url+"/obs/plugins")
    expect(page.locator("#plugin-connection-warning")).to_contain_text("unavailable")
    expect(page.locator(".plugin-card")).to_have_count(0)
    page.locator("#plugin-refresh").click()
    expect(page.locator("#plugin-managed-count")).to_have_text("1")
    expect(page.locator(".plugin-card")).to_have_count(1)
    assert fake.mutations()==[]


def test_issue75_install_cancel_preserves_absent_state(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page)
    launch(page,live_server,fake)
    button=page.get_by_role("button",name="Install plugin")
    expect(button).to_be_enabled()
    act(page,"Install plugin")
    page.get_by_role("button",name="Cancel").click()
    expect(page.locator(".plugin-card")).to_contain_text("Not installed")
    assert fake.mutations()==[]


def test_issue75_install_confirm_uses_only_approved_backend_release(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page)
    launch(page,live_server,fake)
    act(page,"Install plugin")
    expect(page.locator("#plugin-confirm-detail")).to_contain_text("backend-selected")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Installed")
    expect(page.locator(".plugin-card")).to_contain_text("2.0")
    assert len(fake.mutations("obs_plugin.install"))==1
    assert fake.mutations("obs_plugin.install")[0]["payload"]=={"plugin_id":"obs-multi-rtmp"}
    assert fake.mutations("obs_plugin.verify")==[]


def test_issue75_update_changes_version_only_after_backend_response(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UPDATE_AVAILABLE",installed_version="1.0")
    launch(page,live_server,fake)
    expect(page.locator(".plugin-card")).to_contain_text("1.0")
    act(page,"Update plugin")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Installed")
    expect(page.locator(".plugin-card")).to_contain_text("2.0")
    assert len(fake.mutations("obs_plugin.update"))==1
    assert fake.mutations("obs_plugin.install")==[]


def test_issue75_rollback_without_server_proven_baseline_is_disabled(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="VERIFIED",installed_version="2.0",rollback=False)
    launch(page,live_server,fake)
    button=page.get_by_role("button",name="Rollback")
    expect(button).to_be_disabled()
    assert fake.mutations()==[]


def test_issue75_rollback_confirm_restores_backend_reported_version(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="VERIFIED",installed_version="2.0",rollback=True)
    launch(page,live_server,fake)
    act(page,"Rollback")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("1.0")
    assert len(fake.mutations("obs_plugin.rollback"))==1
    assert fake.mutations("obs_plugin.verify")==[]


def test_issue75_streaming_blocks_install_without_stopping_output(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,streaming=True,obs_state="READY")
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Install plugin")).to_be_disabled()
    expect(page.locator("#plugin-output-safety-banner")).to_be_visible()
    expect(page.locator("#plugin-output-safety-banner")).to_contain_text("Live / blocked")
    assert fake.mutations()==[]


def test_issue75_recording_blocks_update_without_stopping_output(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UPDATE_AVAILABLE",installed_version="1.0",
                    recording=True,obs_state="READY")
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Update plugin")).to_be_disabled()
    expect(page.locator("#plugin-output-safety-banner")).to_be_visible()
    assert fake.mutations()==[]


def test_issue75_typed_race_conflict_preserves_old_version(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UPDATE_AVAILABLE",installed_version="1.0")
    fake.fail_operation="plugin_state_conflict"
    launch(page,live_server,fake)
    act(page,"Update plugin")
    confirm(page)
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_state_conflict")
    expect(page.locator(".plugin-card")).to_contain_text("1.0")
    assert len(fake.mutations("obs_plugin.update"))==1


def test_issue75_verify_failure_is_explicit_not_false_success(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="INSTALLED",installed_version="2.0",obs_state="READY")
    fake.fail_operation="plugin_verify_failed"
    launch(page,live_server,fake)
    act(page,"Verify")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Verify failed")
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_verify_failed")
    assert len(fake.mutations("obs_plugin.verify"))==1


def test_issue75_recovery_required_disables_mutations_even_with_release(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="RECOVERY_REQUIRED",installed_version="1.0",rollback=True)
    launch(page,live_server,fake)
    expect(page.locator(".plugin-card")).to_contain_text("Recovery required")
    assert fake.mutations()==[]


def test_issue75_catalog_missing_disables_install_without_fake_source(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,catalog=False)
    launch(page,live_server,fake)
    expect(page.locator("#plugin-release-source")).to_contain_text("EMPTY")
    expect(page.get_by_role("button",name="Install plugin")).to_be_disabled()
    assert fake.mutations()==[]


def test_issue75_keyboard_focus_mobile_and_expand_collapse(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    page.set_viewport_size({"width":360,"height":800})
    page.goto(live_server.base_url+"/obs/plugins")
    header=page.locator(".plugin-card-header")
    expect(header).to_have_attribute("aria-expanded","true")
    header.focus()
    page.keyboard.press("Enter")
    expect(header).to_have_attribute("aria-expanded","false")
    expect(header).to_be_focused()
    page.keyboard.press("Enter")
    expect(header).to_have_attribute("aria-expanded","true")
    expect(page.get_by_role("button",name="Adopt existing")).to_be_enabled()
    page.keyboard.press("Escape")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert fake.mutations()==[]


def test_issue75_timeout_unknown_outcome_disables_repeat_mutation(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    fake.fail_operation="plugin_operation_timeout"
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator("#plugin-connection-warning")).to_contain_text("unknown")
    expect(page.get_by_role("button",name="Adopt existing")).to_be_disabled()
    assert len(fake.mutations("obs_plugin.adopt"))==1
    # A read-only refresh is permitted, but it cannot prove that a timed-out
    # mutation stopped. No blind second request is ever sent.
    page.locator("#plugin-refresh").click()
    expect(page.locator("#plugin-connection-warning")).to_contain_text("unknown")
    assert len(fake.mutations("obs_plugin.adopt"))==1


def test_issue75_confirm_double_activation_submits_one_mutation(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    page.evaluate("""() => {
        const submit=document.getElementById('plugin-confirm-submit');
        submit.click();
        submit.click();
    }""")
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    assert len(fake.mutations("obs_plugin.adopt"))==1


def test_issue75_adopt_with_empty_catalog_does_not_auto_install(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    launch(page,live_server,fake)
    expect(page.locator("#plugin-release-source")).to_contain_text("EMPTY")
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    assert len(fake.mutations("obs_plugin.adopt"))==1
    assert fake.mutations("obs_plugin.install")==[]


def test_issue75_changed_event_refetches_authoritative_status(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="INSTALLED",installed_version="1.0")
    launch(page,live_server,fake)
    baseline=len([r for r in fake.calls if r["operation"]=="obs_plugin.inventory"])
    fake.plugin_state="UPDATE_AVAILABLE"
    fake.revision+=1
    fake.push_changed()
    expect(page.locator(".plugin-card")).to_contain_text("Update available")
    assert len([r for r in fake.calls if r["operation"]=="obs_plugin.inventory"])>baseline
    calls=len([r for r in fake.calls if r["operation"]=="obs_plugin.inventory"])
    # Replayed/lower revision notifications are invalidation hints, not a
    # second authoritative mutation or an opportunity to roll state backwards.
    fake.revision-=1
    fake.push_changed()
    assert len([r for r in fake.calls if r["operation"]=="obs_plugin.inventory"])==calls
    assert fake.mutations()==[]


def test_issue75_restarting_obs_does_not_mark_release_verified(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="RESTART_REQUIRED",installed_version="2.0",obs_state="READY")
    launch(page,live_server,fake)
    act(page,"Restart OBS")
    confirm(page)
    expect(page.locator("#plugin-activity")).to_contain_text("obs.lifecycle.restart")
    assert len(fake.mutations("obs.lifecycle.restart"))==1
    assert fake.mutations("obs_plugin.verify")==[]
    expect(page.locator(".plugin-card")).not_to_contain_text("Verified")


def test_issue75_ready_guard_for_verify(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="INSTALLED",installed_version="2.0",obs_state="STOPPED")
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Verify",exact=True)).to_be_disabled()
    assert fake.mutations()==[]


def test_issue75_readonly_catalog_cannot_override_inventory_allowlist(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,registry=False,catalog=True)
    launch(page,live_server,fake)
    expect(page.locator(".plugin-card")).to_have_count(0)
    assert fake.mutations()==[]


def test_issue75_timeout_remains_fail_closed_after_page_reload(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    fake.fail_operation="plugin_operation_timeout"
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator("#plugin-connection-warning")).to_contain_text("unknown")
    assert len(fake.mutations("obs_plugin.adopt"))==1
    # Browser reload must not turn a timed-out server mutation into permission
    # to repeat it. Backend operation_status reports IDLE, which is inconclusive.
    page.reload()
    expect(page.locator("#plugin-managed-count")).to_have_text("1")
    expect(page.locator("#plugin-connection-warning")).to_contain_text("unknown")
    # Pinned MagicPath now opens the first registry card by default; do not
    # collapse it before asserting fail-closed behavior after a reload.
    expect(page.locator(".plugin-card-header")).to_have_attribute("aria-expanded","true")
    expect(page.get_by_role("button",name="Adopt existing")).to_be_disabled()
    assert len(fake.mutations("obs_plugin.adopt"))==1
    assert any(r["operation"]=="obs_plugin.operation_status" for r in fake.calls)


def test_issue75_timeout_with_late_terminal_success_reconciles_readonly_once(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    fake.fail_operation="plugin_operation_timeout"
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator("#plugin-connection-warning")).to_contain_text("unknown")
    assert len(fake.mutations("obs_plugin.adopt"))==1

    # BE operation journal reports an authoritative post-baseline terminal
    # outcome. A read-only refresh may clear uncertainty; no replay of Adopt.
    fake.plugin_state="LEGACY_ADOPTED"
    fake.revision=11
    fake.status_operation={"state":"SUCCEEDED","operation":"adopt",
                           "operation_id":"be-operation-confirmed-11"}
    page.locator("#plugin-refresh").click()
    expect(page.locator("#plugin-connection-warning")).to_be_hidden()
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    page.locator(".plugin-activity-details").evaluate("el=>el.open=true")
    expect(page.locator("#plugin-activity")).to_contain_text("reconciled-succeeded")
    assert len(fake.mutations("obs_plugin.adopt"))==1
    assert any(r["operation"]=="obs_plugin.operation_status" for r in fake.calls)


def test_issue75_catalog_incompatible_never_exposes_unsafe_install(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="NOT_INSTALLED")
    original=fake.approved_release
    fake.approved_release=lambda: {**original(),"compatibility":"incompatible",
                                   "reason":"OBS version is unsupported"}
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Install plugin")).to_be_disabled()
    expect(page.locator(".plugin-card")).to_contain_text("unsupported")
    assert fake.mutations()==[]


def test_issue75_activity_request_id_matches_actual_ws_request(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    page.locator(".plugin-activity-details").evaluate("el=>el.open=true")
    request=fake.mutations("obs_plugin.adopt")[0]
    expect(page.locator("#plugin-activity")).to_contain_text(request["request_id"])
    expect(page.locator("#plugin-activity")).to_contain_text("adopted")
    assert len(fake.mutations("obs_plugin.adopt"))==1


def test_issue75_install_restart_verify_happy_path_keeps_ops_separate(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="NOT_INSTALLED",obs_state="STOPPED")
    fake.install_requires_restart=True
    launch(page,live_server,fake)
    act(page,"Install plugin")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Restart required")
    expect(page.get_by_role("button",name="Restart OBS")).to_be_disabled()
    assert fake.mutations("obs.lifecycle.restart")==[]
    # OBS is started by a separate operator, not by Adopt/Install.
    fake.operator_starts_obs()
    expect(page.get_by_role("button",name="Restart OBS")).to_be_enabled()
    act(page,"Restart OBS")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Installed")
    expect(page.get_by_role("button",name="Verify",exact=True)).to_be_enabled()
    act(page,"Verify")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Verified")
    operations=[r["operation"] for r in fake.mutations()]
    assert operations==["obs_plugin.install","obs.lifecycle.restart","obs_plugin.verify"]
    assert len(fake.mutations("obs_plugin.install"))==1
    assert len(fake.mutations("obs_plugin.verify"))==1


def test_issue75_update_then_separate_verify_passes_with_new_version(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UPDATE_AVAILABLE",obs_state="STOPPED",
                    installed_version="1.0")
    launch(page,live_server,fake)
    act(page,"Update plugin")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Installed")
    expect(page.locator(".plugin-card")).to_contain_text("2.0")
    assert fake.mutations("obs_plugin.verify")==[]
    fake.operator_starts_obs()
    expect(page.get_by_role("button",name="Verify",exact=True)).to_be_enabled()
    act(page,"Verify")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Verified")
    assert [r["operation"] for r in fake.mutations()]==[
        "obs_plugin.update","obs_plugin.verify"
    ]


def test_issue75_dashboard_card_navigates_to_real_plugin_page(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UNMANAGED")
    page.goto(live_server.base_url+"/obs")
    expect(page.locator("#plugin-dashboard-managed")).to_have_text("1")
    page.locator('a[href="/obs/plugins"]').click()
    expect(page).to_have_url(live_server.base_url+"/obs/plugins")
    expect(page.get_by_role("heading",name="OBS Plugin Manager")).to_be_visible()
    expect(page.locator(".plugin-card")).to_have_count(1)
    assert fake.mutations()==[]


def test_issue75_install_backend_conflict_preserves_not_installed(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="NOT_INSTALLED")
    fake.fail_operation="plugin_state_conflict"
    launch(page,live_server,fake)
    act(page,"Install plugin")
    confirm(page)
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_state_conflict")
    expect(page.locator(".plugin-card")).to_contain_text("Not installed")
    assert len(fake.mutations("obs_plugin.install"))==1


def test_issue75_manual_rollback_then_verify_restored_baseline(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="VERIFIED",rollback=True,installed_version="2.0")
    launch(page,live_server,fake)
    act(page,"Rollback")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("1.0")
    fake.operator_starts_obs()
    expect(page.get_by_role("button",name="Verify",exact=True)).to_be_enabled()
    act(page,"Verify")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Verified")
    expect(page.locator(".plugin-card")).to_contain_text("1.0")
    assert [r["operation"] for r in fake.mutations()]==[
        "obs_plugin.rollback","obs_plugin.verify"
    ]


def test_issue75_vendor_unavailable_verify_failure_is_not_pass(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="INSTALLED",installed_version="2.0",obs_state="READY")
    fake.fail_operation="plugin_verify_failed"
    launch(page,live_server,fake)
    act(page,"Verify")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Verify failed")
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_verify_failed")
    expect(page.locator("#plugin-notice")).to_contain_text("vendor")
    assert len(fake.mutations("obs_plugin.verify"))==1


def test_issue75_adopt_streaming_and_recording_block_without_auto_stop(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",streaming=True,obs_state="READY")
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Adopt existing")).to_be_disabled()
    assert fake.mutations()==[]


def test_issue75_backend_adoption_required_does_not_fake_install(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="LEGACY_ADOPTED",installed_version=None)
    fake.fail_operation="plugin_adoption_required"
    launch(page,live_server,fake)
    act(page,"Install approved release")
    confirm(page)
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_adoption_required")
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    assert len(fake.mutations("obs_plugin.install"))==1
    assert fake.mutations("obs_plugin.adopt")==[]


def test_issue75_failed_rollback_requires_recovery_not_false_ready(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="VERIFIED",rollback=True,installed_version="2.0")
    fake.fail_operation="plugin_rollback_failed"
    launch(page,live_server,fake)
    act(page,"Rollback")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Recovery required")
    expect(page.locator("#plugin-notice")).to_contain_text("Rollback failed")
    expect(page.get_by_role("button",name="Rollback")).to_be_disabled()
    assert len(fake.mutations("obs_plugin.rollback"))==1


def test_issue75_stale_open_adopt_dialog_refuses_newly_invalid_mutation(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    # While confirmation is open a second operator adopted the plugin.
    # The browser must revalidate current state rather than submit stale intent.
    fake.plugin_state="LEGACY_ADOPTED"
    fake.revision+=1
    fake.push_changed()
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    page.get_by_role("button",name="Confirm",exact=True).click()
    expect(page.locator("#plugin-notice")).to_contain_text("Only an existing unmanaged")
    assert fake.mutations("obs_plugin.adopt")==[]


def test_issue75_already_adopted_is_idempotent_but_not_approved_or_verified(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    fake.already_adopted=True
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    expect(page.locator(".plugin-card")).not_to_contain_text("Verified")
    page.locator(".plugin-activity-details").evaluate("el=>el.open=true")
    expect(page.locator("#plugin-activity")).to_contain_text("already_adopted")
    assert len(fake.mutations("obs_plugin.adopt"))==1
    assert fake.mutations("obs_plugin.install")==[]


def test_issue75_legacy_adopt_empty_catalog_then_approved_release_enables_install(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    expect(page.get_by_role("button",name="Install approved release")).to_be_disabled()
    assert fake.mutations("obs_plugin.install")==[]
    # Release approval becomes available later; only a fresh BE catalog read
    # can enable Install. Adoption itself never downloads an artifact.
    fake.has_catalog=True
    page.locator("#plugin-refresh").click()
    expect(page.get_by_role("button",name="Install approved release")).to_be_enabled()
    assert len(fake.mutations("obs_plugin.adopt"))==1
    assert fake.mutations("obs_plugin.install")==[]


def test_issue75_adopt_recording_guard_blocks_even_when_obs_state_claims_stopped(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False,
                    obs_state="STOPPED",recording=True)
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Adopt existing")).to_be_disabled()
    assert fake.mutations()==[]


def test_issue75_adopt_backend_409_race_reconciles_without_stopping_obs(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    fake.fail_operation="plugin_state_conflict"
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_state_conflict")
    expect(page.locator(".plugin-card")).to_contain_text("Existing")
    assert len(fake.mutations("obs_plugin.adopt"))==1
    assert fake.mutations("obs.lifecycle.stop")==[]



def test_issue75_design_aligned_cards_keep_live_ws_counts_and_logical_activity(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    page.set_viewport_size({"width":390,"height":844})
    launch(page,live_server,fake)
    expect(page.locator(".plugin-manager-page .topbar")).to_have_count(0)
    assert page.locator(".plugin-shell").evaluate("el => el.getBoundingClientRect().width") <= 448
    expect(page.locator("#plugin-managed-count")).to_have_text("1")
    expect(page.locator("#plugin-installed-count")).to_have_text("1")
    expect(page.locator("#plugin-operation-count")).to_have_text("0")
    expect(page.locator(".plugin-activity-summary")).to_be_visible()
    expect(page.locator("#plugin-error-count")).to_be_visible()
    expect(page.locator("#plugin-error-pill")).to_have_text("0 errors")
    assert fake.mutations()==[]
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    # BE adapter records requested and terminal events with same request_id,
    # but a single user action is one operation in the summary.
    expect(page.locator("#plugin-operation-count")).to_have_text("1")
    expect(page.locator("#plugin-last-event")).to_contain_text("adopt")
    expect(page.locator("#plugin-error-count")).to_have_text("0")
    assert len(fake.mutations("obs_plugin.adopt"))==1


def test_issue75_not_installed_card_matches_design_without_invented_baseline(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="NOT_INSTALLED",installed_version=None)
    page.set_viewport_size({"width":390,"height":844})
    launch(page,live_server,fake)
    expect(page.locator(".plugin-card-header")).to_have_attribute("aria-expanded","true")
    expect(page.locator(".plugin-install-preview .plugin-action")).to_have_text("Install plugin")
    expect(page.locator(".plugin-install-source-note")).to_contain_text("StreamOps managed distribution")
    expect(page.locator(".plugin-install-source-note")).to_contain_text("No arbitrary external release URL")
    expect(page.locator(".plugin-card")).not_to_contain_text("Managed baseline")
    assert fake.mutations()==[]
    act(page,"Install plugin")
    page.get_by_role("button",name="Cancel",exact=True).click()
    assert fake.mutations()==[]


def test_issue75_plugin_purpose_and_catalog_status_preserve_backend_identity(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="NOT_INSTALLED",installed_version=None)
    page.set_viewport_size({"width":360,"height":800})
    launch(page,live_server,fake)
    expect(page.locator(".plugin-purpose-line")).to_have_text(
        "Multi-destination streaming plugin")
    expect(page.locator(".plugin-heading-text")).to_have_attribute(
        "title","obs-multi-rtmp")
    expect(page.locator("#plugin-release-source")).to_contain_text("READY")
    expect(page.locator("#plugin-release-source")).to_be_visible()
    heading=page.locator('[aria-labelledby="plugin-managed-title"]>.plugin-section-heading')
    catalog=page.locator("#plugin-release-source")
    assert catalog.evaluate("(el)=>el.getBoundingClientRect().bottom") <= (
        heading.evaluate("(el)=>el.getBoundingClientRect().bottom")+1
    ),"Release catalog metadata must not add an extra row above the card"
    assert fake.mutations()==[]


def test_issue75_mobile_purpose_uses_full_card_width_under_heading(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="NOT_INSTALLED")
    page.set_viewport_size({"width":390,"height":844})
    launch(page,live_server,fake)
    heading=page.locator(".plugin-card-header")
    purpose=page.locator(".plugin-purpose-line")
    assert purpose.evaluate("el => getComputedStyle(el).gridColumnEnd") in {"-1","-1"}
    assert purpose.evaluate("(el)=>el.getBoundingClientRect().width") >= (
        heading.evaluate("(el)=>el.getBoundingClientRect().width")-36
    )
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert fake.mutations()==[]


def test_issue75_rollback_alias_cannot_override_backend_backup_denial(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="VERIFIED",rollback=False,installed_version="2.0")
    fake.rollback_alias_override=True
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Rollback")).to_be_disabled()
    assert fake.mutations()==[], "Contradictory compatibility alias is not backup evidence"


def test_issue75_rollback_missing_canonical_proof_remains_disabled(
    page:Page,live_server:BrowserTestServer
):
    fake=ScenarioWS(page,plugin_state="VERIFIED",rollback=False,installed_version="2.0")
    fake.rollback_missing_proof=True
    fake.rollback_alias_override=True
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Rollback")).to_be_disabled()
    assert fake.mutations()==[], "A legacy boolean cannot authorize Rollback"




def test_issue75_two_tabs_reconcile_adopt_without_duplicate_mutation(
    page:Page,live_server:BrowserTestServer
):
    """E2E-19/36: both WS observers share backend state; stale modal is safe."""
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    second=page.context.new_page()
    second.route_web_socket("**/api/v1/obs/plugins/ws",fake.plugin_socket)
    second.route_web_socket("**/api/v1/obs/ws",fake.obs_socket)
    try:
        launch(page,live_server,fake)
        launch(second,live_server,fake)
        assert len([r for r in fake.calls if r["operation"]=="obs_plugin.subscribe"])>=2
        # Open the second tab's confirmation before the first tab changes state.
        act(second,"Adopt existing")
        act(page,"Adopt existing")
        confirm(page)
        expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
        expect(second.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
        # The second tab MUST recheck fresh backend state on Confirm; it may
        # not dispatch a stale second Adopt even though its modal stayed open.
        confirm(second)
        expect(second.locator("#plugin-notice")).to_contain_text("Only an existing unmanaged")
        assert len(fake.mutations("obs_plugin.adopt"))==1
        assert fake.mutations("obs_plugin.install")==[]
    finally:
        second.close()


def test_issue75_refresh_while_backend_operation_running_reconciles_without_replay(
    page:Page,live_server:BrowserTestServer
):
    """E2E-18: read-only refresh after uncertain mutation cannot repeat it."""
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=False)
    fake.fail_operation="plugin_operation_timeout"
    launch(page,live_server,fake)
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator("#plugin-connection-warning")).to_contain_text("unknown")
    assert len(fake.mutations("obs_plugin.adopt"))==1
    # The server still has an active operation. Refresh is read-only and does
    # not grant Adopt/Install permission or infer a successful outcome.
    fake.status_operation={"state":"RUNNING","operation":"adopt","operation_id":"still-active"}
    page.locator("#plugin-refresh").click()
    expect(page.locator("#plugin-connection-warning")).to_contain_text("unknown")
    expect(page.get_by_role("button",name="Adopt existing")).to_be_disabled()
    assert len(fake.mutations("obs_plugin.adopt"))==1
    assert any(x["operation"]=="obs_plugin.operation_status" for x in fake.calls)
    # A higher revision AND a matching server terminal operation reconcile
    # uncertainty without client replay or synthetic install/verify.
    fake.plugin_state="LEGACY_ADOPTED"
    fake.revision+=1
    fake.status_operation={"state":"SUCCEEDED","operation":"adopt",
                           "operation_id":"confirmed-adopt"}
    page.locator("#plugin-refresh").click()
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    expect(page.locator("#plugin-connection-warning")).to_be_hidden()
    assert len(fake.mutations("obs_plugin.adopt"))==1
    assert fake.mutations("obs_plugin.install")==[]
    assert fake.mutations("obs_plugin.verify")==[]


def test_issue75_full_adopt_install_restart_verify_rollback(
    page:Page,live_server:BrowserTestServer
):
    """E2E-33: each operation is explicit and authorized by refreshed BE state."""
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=True,
                    obs_state="STOPPED",installed_version="0.7.2",rollback=False)
    fake.install_requires_restart=True
    launch(page,live_server,fake)

    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    assert fake.mutations("obs_plugin.install")==[]
    assert fake.mutations("obs.lifecycle.restart")==[]
    assert fake.mutations("obs_plugin.verify")==[]

    act(page,"Install approved release")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Restart required")
    assert fake.mutations("obs.lifecycle.restart")==[]
    fake.operator_starts_obs()
    expect(page.get_by_role("button",name="Restart OBS")).to_be_enabled()
    act(page,"Restart OBS")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Installed")
    assert fake.mutations("obs_plugin.verify")==[]

    act(page,"Verify")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Verified")
    assert fake.mutations("obs_plugin.rollback")==[]

    # Backup eligibility only becomes true after the backend reports proof.
    fake.rollback=True
    fake.revision+=1
    fake.push_changed()
    expect(page.get_by_role("button",name="Rollback")).to_be_enabled()
    act(page,"Rollback")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("1.0")
    assert [r["operation"] for r in fake.mutations()]==[
        "obs_plugin.adopt","obs_plugin.install","obs.lifecycle.restart",
        "obs_plugin.verify","obs_plugin.rollback"]
    assert fake.mutations("obs.lifecycle.stop")==[]


def test_issue75_dashboard_and_manager_observers_share_authoritative_revision(
    page:Page,live_server:BrowserTestServer
):
    """E2E-36: Dashboard and Manager are independent WS consumers."""
    fake=ScenarioWS(page,plugin_state="INSTALLED",installed_version="1.0")
    dashboard=page.context.new_page()
    dashboard.route_web_socket("**/api/v1/obs/plugins/ws",fake.plugin_socket)
    dashboard.route_web_socket("**/api/v1/obs/ws",fake.obs_socket)
    try:
        launch(page,live_server,fake)
        dashboard.goto(live_server.base_url+"/obs")
        expect(dashboard.locator("#plugin-dashboard-managed")).to_have_text("1")
        first=len([r for r in fake.calls if r["operation"]=="obs_plugin.inventory"])
        fake.plugin_state="UPDATE_AVAILABLE"
        fake.revision+=1
        fake.push_changed()
        expect(page.locator(".plugin-card")).to_contain_text("Update available")
        expect(dashboard.locator("#plugin-dashboard-state")).not_to_have_text("Loading")
        assert len([r for r in fake.calls if r["operation"]=="obs_plugin.inventory"])>=first+2
        # Replayed revisions cannot trigger an inventory request loop.
        requests=len([r for r in fake.calls if r["operation"]=="obs_plugin.inventory"])
        fake.revision-=1
        fake.push_changed()
        assert len([r for r in fake.calls if r["operation"]=="obs_plugin.inventory"])==requests
        assert fake.mutations()==[]
    finally:
        dashboard.close()


def test_issue75_legacy_adopt_typed_failure_and_recovery_never_auto_installs(
    page:Page,live_server:BrowserTestServer
):
    """E2E-32: an unmanaged legacy plugin must be adopted before Install."""
    fake=ScenarioWS(page,plugin_state="UNMANAGED",catalog=True,
                    installed_version="0.7.2",obs_state="STOPPED")
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Adopt existing")).to_be_enabled()
    expect(page.get_by_role("button",name="Install approved release")).to_have_count(0)
    fake.fail_operation="plugin_adopt_failed"
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_adopt_failed")
    expect(page.locator(".plugin-card")).to_contain_text("unmanaged")
    assert fake.plugin_state=="UNMANAGED"
    assert fake.mutations("obs_plugin.install")==[]
    assert len(fake.mutations("obs_plugin.adopt"))==1

    # A typed backend recovery state must NOT cause a synthetic Install or
    # leave Adopt enabled against a possibly interrupted file transaction.
    fake.fail_operation="plugin_recovery_required"
    act(page,"Adopt existing")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Recovery required")
    expect(page.get_by_role("button",name="Adopt existing")).to_have_count(0)
    assert fake.mutations("obs_plugin.install")==[]
    assert len(fake.mutations("obs_plugin.adopt"))==2


def test_issue75_legacy_install_recovery_and_rollback_failure_are_fail_closed(
    page:Page,live_server:BrowserTestServer
):
    """E2E-35: failed legacy Install never becomes verified or retried."""
    fake=ScenarioWS(page,plugin_state="LEGACY_ADOPTED",catalog=True,
                    installed_version="0.7.2",obs_state="STOPPED")
    launch(page,live_server,fake)
    fake.fail_operation="plugin_recovery_required"
    act(page,"Install approved release")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Recovery required")
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_recovery_required")
    assert fake.installed_version=="0.7.2"
    assert len(fake.mutations("obs_plugin.install"))==1
    assert fake.mutations("obs_plugin.rollback")==[]
    assert fake.mutations("obs_plugin.verify")==[]

    # A read-only refresh retains recovery status until the backend reports
    # another authoritative revision; it may not attempt any rollback itself.
    page.locator("#plugin-refresh").click()
    expect(page.locator(".plugin-card")).to_contain_text("Recovery required")
    assert len(fake.mutations("obs_plugin.install"))==1
    assert fake.mutations("obs_plugin.rollback")==[]


class RestartTransientDisconnectScenario(ScenarioWS):
    """Force the actual browser WS transport to close while Restart is pending.

    Restart response deliberately stays pending until the test explicitly
    acknowledges it. Real reconnect and subscription logic must run.
    """
    def __init__(self,page):
        super().__init__(page,plugin_state="RESTART_REQUIRED",
                         installed_version="2.0",obs_state="READY")
        self.pending_restart=None

    def obs_socket(self,ws):
        self.obs_sockets.append(ws)

        def snapshot():
            ws.send(json.dumps({"type":"event","event":"obs.snapshot","data":{
                "runtime":{"state":self.obs_state,
                  "output":{"streaming":False,"recording":False},
                  "websocket":{"connected":self.obs_state=="READY"}}}}))
        snapshot()

        def handle(raw):
            req=json.loads(raw)
            self.calls.append(req)
            if req["operation"] in {
                "source_catalog.list","scene_profile_templates.list",
                "scene_profiles.list","inventory.get"
            }:
                reads={
                    "source_catalog.list":{"sources":[]},
                    "scene_profile_templates.list":{"templates":[]},
                    "scene_profiles.list":{"profiles":[]},
                    "inventory.get":{"options":{}},
                }
                ws.send(json.dumps({"type":"response","request_id":req["request_id"],
                                    "ok":True,"data":reads[req["operation"]]}))
                return
            assert req["operation"]=="obs.lifecycle.restart",req["operation"]
            assert self.pending_restart is None,"only one OBS restart request"
            self.pending_restart=(ws,req["request_id"])
            self.obs_state="STOPPED"
            snapshot()
            # The OBS lifecycle restarts the plugin WS: no explicit response
            # or Verify success can be inferred from this transient disconnect.
            for connection in list(self.sockets):
                connection.close()
        ws.on_message(handle)

    def finish_restart(self):
        assert self.pending_restart is not None
        ws,request_id=self.pending_restart
        self.pending_restart=None
        self.obs_state="READY"
        self.plugin_state="INSTALLED"
        self.revision+=1
        ws.send(json.dumps({"type":"response","request_id":request_id,
                            "ok":True,"data":{"state":"READY"}}))
        ws.send(json.dumps({"type":"event","event":"obs.snapshot","data":{
            "runtime":{"state":"READY",
              "output":{"streaming":False,"recording":False},
              "websocket":{"connected":True}}}}))
        # Only a newly subscribed WS observer receives the change.
        self.sockets[-1].send(json.dumps({
            "type":"event","event":"obs_plugin.changed",
            "data":{"plugin_id":"obs-multi-rtmp","revision":self.revision,
                    "resources":["status","operation"]},
        }))


def test_issue75_restart_transient_ws_disconnect_waits_for_lifecycle_ack(
    page:Page,live_server:BrowserTestServer,
):
    """E2E-16: socket restart is not success; only explicit ack completes it."""
    fake=RestartTransientDisconnectScenario(page)
    launch(page,live_server,fake)
    act(page,"Restart OBS")
    # Confirmation closes while async operation is still running.
    confirm(page)
    expect(page.locator("#plugin-obs-state")).to_have_text("STOPPED")
    expect(page.locator("#plugin-activity")).to_contain_text(
        "obs.lifecycle.restart · requested"
    )
    expect(page.locator("#plugin-activity")).not_to_contain_text(
        "obs.lifecycle.restart · completed"
    )
    expect(page.locator(".plugin-card")).not_to_contain_text("Verified")
    assert fake.pending_restart is not None
    assert len(fake.mutations("obs.lifecycle.restart"))==1
    assert fake.mutations("obs_plugin.verify")==[]

    # Poll boundedly for a *second* WS route, rather than sleeping for a
    # guessed reconnection delay. The route re-subscribes and reads inventory.
    for _ in range(35):
        if len(fake.sockets)>=2:
            break
        page.wait_for_timeout(150)
    assert len(fake.sockets)>=2,"browser did not reconnect the plugin WS"
    assert len([x for x in fake.calls
                if x["operation"]=="obs_plugin.subscribe"])>=2
    expect(page.locator("#plugin-activity")).not_to_contain_text(
        "obs.lifecycle.restart · completed"
    )
    # No mutation or Verify occurred merely because the plugin WS returned.
    assert [x["operation"] for x in fake.mutations()]==["obs.lifecycle.restart"]

    fake.finish_restart()
    expect(page.locator("#plugin-activity")).to_contain_text(
        "obs.lifecycle.restart · completed"
    )
    expect(page.locator(".plugin-card")).to_contain_text("Installed")
    expect(page.locator(".plugin-card")).not_to_contain_text("Verified")
    assert [x["operation"] for x in fake.mutations()]==["obs.lifecycle.restart"]
