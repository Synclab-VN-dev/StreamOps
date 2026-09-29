from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import BrowserTestServer, wait_until


pytestmark = pytest.mark.only_browser("chromium")


def test_obs_runtime_status_and_output_guards(page: Page, live_server: BrowserTestServer) -> None:
    page.goto(f"{live_server.base_url}/obs")

    expect(page.get_by_role("heading", name="OBS Runtime")).to_be_visible()
    expect(page.locator("#obs-state")).to_have_text("READY")
    expect(page.locator("#obs-pid")).to_have_text("5100")
    expect(page.locator("#obs-session")).to_have_text("7")
    expect(page.locator("#obs-active-session")).to_have_text("7")
    expect(page.locator("#obs-interactive")).to_have_text("Yes")
    expect(page.locator("#obs-websocket")).to_have_text("Connected")
    expect(page.locator("#obs-version")).to_have_text("32.0.0-test")
    expect(page.locator("#obs-websocket-version")).to_have_text("5.6.0-test")
    expect(page.locator("#obs-streaming")).to_have_text("No")
    expect(page.locator("#obs-recording")).to_have_text("No")
    expect(page.get_by_role("button", name="Start OBS", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Stop OBS")).to_be_enabled()
    expect(page.get_by_role("button", name="Restart OBS")).to_be_enabled()

    live_server.obs.set_ready(5200, recording=True)
    page.reload()
    expect(page.locator("#obs-pid")).to_have_text("5200")
    expect(page.locator("#obs-recording")).to_have_text("Yes")
    expect(page.get_by_role("button", name="Stop OBS")).to_be_disabled()
    expect(page.get_by_role("button", name="Restart OBS")).to_be_disabled()


def test_start_pending_success_and_no_double_trigger(page: Page, live_server: BrowserTestServer) -> None:
    live_server.obs.set_stopped()
    live_server.obs.prepare_launch(6200)
    page.goto(f"{live_server.base_url}/obs")

    expect(page.locator("#obs-state")).to_have_text("STOPPED")
    button = page.get_by_role("button", name="Start OBS", exact=True)
    expect(button).to_be_enabled()

    button.click()
    wait_until(live_server.obs.launch_started.is_set)
    expect(page.locator("#obs-state")).to_have_text("STARTING")
    expect(page.get_by_role("button", name="Start OBS", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Stop OBS")).to_be_disabled()
    expect(page.get_by_role("button", name="Restart OBS")).to_be_disabled()

    page.locator("#start-button").evaluate("button => button.click()")
    assert live_server.obs.launch_calls == 1

    live_server.obs.release_launch()
    expect(page.locator("#obs-state")).to_have_text("READY")
    expect(page.locator("#obs-pid")).to_have_text("6200")
    expect(page.locator("#obs-last-operation")).to_contain_text("start · success")
    expect(page.locator("#activity-log")).to_contain_text("Start completed: READY")


def test_running_without_websocket_is_not_presented_as_ready(
    page: Page, live_server: BrowserTestServer
) -> None:
    live_server.obs.set_ready(5300)
    live_server.obs.set_websocket_unavailable()

    page.goto(f"{live_server.base_url}/obs")

    expect(page.locator("#obs-state")).to_have_text("RUNNING_NO_WEBSOCKET")
    expect(page.locator("#obs-websocket")).to_have_text("Unavailable")
    expect(page.locator("#obs-streaming")).to_have_text("Unknown")
    expect(page.get_by_role("button", name="Start OBS", exact=True)).to_be_enabled()
    expect(page.get_by_role("button", name="Stop OBS")).to_be_disabled()
    expect(page.get_by_role("button", name="Restart OBS")).to_be_disabled()


def test_restart_pending_returns_to_ready_with_new_pid(
    page: Page, live_server: BrowserTestServer
) -> None:
    live_server.obs.set_ready(5400)
    live_server.obs.prepare_launch(6400)
    page.goto(f"{live_server.base_url}/obs")
    expect(page.locator("#obs-pid")).to_have_text("5400")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Restart OBS").click()
    wait_until(live_server.obs.launch_started.is_set)
    expect(page.locator("#obs-state")).to_have_text("STARTING")
    expect(page.get_by_role("button", name="Restart OBS")).to_be_disabled()

    live_server.obs.release_launch()
    expect(page.locator("#obs-state")).to_have_text("READY")
    expect(page.locator("#obs-pid")).to_have_text("6400")
    expect(page.locator("#obs-last-operation")).to_contain_text("restart · success")
    expect(page.locator("#activity-log")).to_contain_text("Restart completed: READY")

def test_readiness_timeout_is_visible_to_operator(page: Page, live_server: BrowserTestServer) -> None:
    live_server.obs.set_stopped()
    live_server.obs.set_websocket_unavailable()
    page.goto(f"{live_server.base_url}/obs")

    page.get_by_role("button", name="Start OBS", exact=True).click()

    expect(page.locator("#error-message")).to_contain_text("did not become ready")
    expect(page.locator("#activity-log")).to_contain_text("Start failed:")
    expect(page.locator("#obs-state")).to_have_text("RUNNING_NO_WEBSOCKET")
    expect(page.get_by_role("button", name="Start OBS", exact=True)).to_be_enabled()


def test_obs_page_is_usable_on_mobile_viewport(page: Page, live_server: BrowserTestServer) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_server.base_url}/obs")

    expect(page.get_by_role("heading", name="OBS", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="OBS Runtime")).to_be_visible()
    expect(page.get_by_role("button", name="Stop OBS", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Restart OBS", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Activity Log")).to_be_visible()

