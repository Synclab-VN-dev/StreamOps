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
        self.status_operation={"state":"IDLE","operation_id":None}
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
        return current

    def approved_release(self):
        return {"plugin_id":"obs-multi-rtmp","available_version":self.release_version,
                "installable":True,"compatibility":"compatible",
                "release_ref":"v"+self.release_version}

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
                        self.plugin_state="VERIFY_FAILED"
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
                    self.plugin_state="INSTALLED"
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
                      "result":"adopted" if operation=="adopt" else "completed",
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
        def snapshot():
            ws.send(json.dumps({"type":"event","event":"obs.snapshot","data":{
                "runtime":{"state":self.obs_state,
                  "output":{"streaming":self.streaming,"recording":self.recording},
                  "websocket":{"connected":self.obs_state=="READY"}}}}))
        snapshot()

        def handle(raw):
            req=json.loads(raw);self.calls.append(req)
            if req["operation"] != "obs.lifecycle.restart":
                raise AssertionError("No background OBS mutation is permitted")
            self.obs_state="READY"
            ws.send(json.dumps({"type":"response","request_id":req["request_id"],
                                "ok":True,"data":{"state":"READY"}}))
            snapshot()
        ws.on_message(handle)

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
    expect(page.locator("#plugin-managed-count")).to_have_text("1" if scenario.registry else "0")
    if scenario.registry:
        expect(page.locator(".plugin-card")).to_have_count(1)
        page.locator(".plugin-card-header").click()


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
    assert fake.mutations()==[]


def test_issue75_recording_blocks_update_without_stopping_output(page:Page,live_server:BrowserTestServer):
    fake=ScenarioWS(page,plugin_state="UPDATE_AVAILABLE",installed_version="1.0",
                    recording=True,obs_state="READY")
    launch(page,live_server,fake)
    expect(page.get_by_role("button",name="Update plugin")).to_be_disabled()
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
    expect(header).to_have_attribute("aria-expanded","false")
    header.focus()
    page.keyboard.press("Enter")
    expect(header).to_have_attribute("aria-expanded","true")
    expect(page.get_by_role("button",name="Adopt existing")).to_be_enabled()
    page.keyboard.press("Escape")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert fake.mutations()==[]
