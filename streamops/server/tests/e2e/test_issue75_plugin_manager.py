"""#75 FE-only real-browser E2E with contract-compatible mock WS; never mutates OBS."""
from __future__ import annotations

import json
import pytest
from playwright.sync_api import Page, expect

from .conftest import BrowserTestServer

pytestmark = pytest.mark.only_browser("chromium")


class MockPluginWebSocket:
    """Production UI over simulated WS; NOT evidence that PR #52 supports list/catalog WS."""

    def __init__(self, page: Page, *, plugin_state: str = "UNMANAGED", obs_state: str = "STOPPED"):
        self.plugin_state = plugin_state
        self.obs_state = obs_state
        self.calls: list[dict] = []
        self.sockets = []
        page.route_web_socket("**/api/v1/obs/plugins/ws", self.plugin_socket)
        page.route_web_socket("**/api/v1/obs/ws", self.obs_socket)

    def status(self):
        return {
            "plugin_id": "obs-multi-rtmp",
            "display_name": "Multiple RTMP Outputs",
            "state": self.plugin_state,
            "installed": self.plugin_state != "NOT_INSTALLED",
            "managed": self.plugin_state not in ("NOT_INSTALLED", "UNMANAGED"),
            "adoptable": self.plugin_state == "UNMANAGED",
            "compatible": True, "loaded": False,
            "installed_version": None, "available_version": None,
            "restart_required": False, "last_verification": None,
        }

    def plugin_socket(self, ws):
        self.sockets.append(ws)

        def handle(message):
            request = json.loads(message)
            self.calls.append(request)
            operation = request["operation"]
            data = None
            if operation == "obs_plugin.inventory":
                data = {"plugins": [self.status()]}
            elif operation == "obs_plugin.available":
                data = {"plugins": [], "source_state": "EMPTY"}
            elif operation == "obs_plugin.adopt":
                if self.obs_state != "STOPPED":
                    ws.send(json.dumps({
                        "type": "response", "request_id": request["request_id"],
                        "ok": False,
                        "error": {"code": "plugin_adopt_requires_obs_stopped",
                                  "message": "OBS must be STOPPED."},
                    }))
                    return
                self.plugin_state = "LEGACY_ADOPTED"
                data = {**self.status(), "operation": "adopt", "result": "adopted", "previous_version": None}
            else:
                ws.send(json.dumps({
                    "type": "response", "request_id": request["request_id"], "ok": False,
                    "error": {"code": "unknown_operation", "message": "Unsupported operation."},
                }))
                return
            ws.send(json.dumps({
                "type": "response", "request_id": request["request_id"], "ok": True, "data": data,
            }))
            if operation == "obs_plugin.adopt":
                ws.send(json.dumps({"type": "event", "event": "obs_plugin.changed", "data": {"plugin_id": "obs-multi-rtmp"}}))

        ws.on_message(handle)

    def obs_socket(self, ws):
        ws.send(json.dumps({
            "type": "event", "event": "obs.snapshot",
            "data": {"runtime": {
                "state": self.obs_state,
                "websocket": {"connected": self.obs_state == "READY"},
                "output": {"streaming": False, "recording": False},
            }},
        }))

        def handle(message):
            request = json.loads(message)
            self.calls.append(request)
            ws.send(json.dumps({
                "type": "response", "request_id": request["request_id"],
                "ok": False, "error": {"code": "unsafe_operation", "message": "No OBS mutations in FE test"},
            }))
        ws.on_message(handle)


def test_issue75_adopt_is_explicit_and_does_not_stop_obs(page: Page, live_server: BrowserTestServer):
    fake = MockPluginWebSocket(page)
    page.goto(live_server.base_url + "/obs/plugins")
    expect(page.locator("#plugin-managed-count")).to_have_text("1")
    expect(page.locator(".plugin-card")).to_have_count(1)
    page.locator(".plugin-card-header").click()
    adopt = page.get_by_role("button", name="Adopt existing")
    expect(adopt).to_be_enabled()

    adopt.click()
    expect(page.get_by_role("heading", name="Adopt existing plugin?")).to_be_visible()
    page.get_by_role("button", name="Cancel").click()
    assert not [req for req in fake.calls if req["operation"] == "obs_plugin.adopt"]

    adopt.click()
    page.get_by_role("button", name="Confirm").click()
    expect(page.locator(".plugin-card")).to_contain_text("Legacy baseline adopted")
    expect(page.locator("#plugin-activity")).to_contain_text("adopted")
    assert len([req for req in fake.calls if req["operation"] == "obs_plugin.adopt"]) == 1
    assert not [req for req in fake.calls if req["operation"] == "obs.lifecycle.stop"]
    expect(page.locator(".plugin-card")).not_to_contain_text("Verified")


def test_issue75_adopt_disabled_if_obs_running(page: Page, live_server: BrowserTestServer):
    fake = MockPluginWebSocket(page, obs_state="READY")
    page.goto(live_server.base_url + "/obs/plugins")
    expect(page.locator("#plugin-managed-count")).to_have_text("1")
    page.locator(".plugin-card-header").click()
    adopt = page.get_by_role("button", name="Adopt existing")
    expect(adopt).to_be_disabled()
    expect(page.locator(".plugin-disabled-reason")).to_contain_text("stopped separately")
    assert not [req for req in fake.calls if req["operation"] == "obs_plugin.adopt"]


def test_issue75_empty_catalog_has_no_install_source(page: Page, live_server: BrowserTestServer):
    fake = MockPluginWebSocket(page, plugin_state="NOT_INSTALLED")
    page.goto(live_server.base_url + "/obs/plugins")
    expect(page.locator("#plugin-release-source")).to_have_text("Release catalog: EMPTY")
    page.locator(".plugin-card-header").click()
    expect(page.get_by_role("button", name="Install plugin")).to_be_disabled()
    assert not [req for req in fake.calls if req["operation"] == "obs_plugin.install"]


def test_issue75_mobile_has_no_horizontal_overflow(page: Page, live_server: BrowserTestServer):
    MockPluginWebSocket(page)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(live_server.base_url + "/obs/plugins")
    expect(page.locator("#plugin-managed-count")).to_have_text("1")
    expect(page.get_by_role("heading", name="OBS Plugin Manager")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
