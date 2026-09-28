from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import BrowserTestServer, INTERNAL_LOG_SENTINEL, wait_until


pytestmark = pytest.mark.only_browser("chromium")


def test_steam_status_panel_renders_api_fields(page: Page, live_server: BrowserTestServer) -> None:
    page.goto(f"{live_server.base_url}/steam")

    expect(page.get_by_role("heading", name="Steam Process Status")).to_be_visible()
    expect(page.locator("#steam-state")).to_have_text("Running")
    expect(page.locator("#steam-pid")).to_have_text("2100")
    expect(page.locator("#steam-started")).not_to_have_text("--")
    expect(page.locator("#steam-uptime")).to_have_text("01:02:03")
    expect(page.locator("#steam-session")).to_have_text("7")
    expect(page.locator("#steam-interactive")).to_have_text("Yes")
    expect(page.locator("#steam-installation")).to_have_text("Detected")
    expect(page.get_by_role("button", name="Restart in Big Picture")).to_be_enabled()


def test_restart_pending_success_and_no_double_trigger(
    page: Page, live_server: BrowserTestServer
) -> None:
    live_server.steam.prepare_restart_success(3200)
    page.goto(f"{live_server.base_url}/steam")
    button = page.get_by_role("button", name="Restart in Big Picture")
    expect(button).to_be_enabled()
    status_calls = live_server.steam.status_calls

    page.once("dialog", lambda dialog: dialog.accept())
    button.click()
    wait_until(live_server.steam.restart_started.is_set)
    expect(page.locator("#steam-state")).to_have_text("Restarting")
    expect(page.locator("#steam-pid")).to_have_text("--")
    expect(page.locator("#steam-status-panel")).to_have_attribute("aria-busy", "true")
    expect(page.get_by_role("button", name="Restarting...")).to_be_disabled()

    page.locator("#restart-button").evaluate("button => button.click()")
    assert live_server.steam.restart_calls == 1

    live_server.steam.release_restart()
    expect(page.locator("#steam-pid")).to_have_text("3200")
    expect(page.locator("#steam-state")).to_have_text("Running")
    expect(page.get_by_role("button", name="Restart in Big Picture")).to_be_enabled()
    assert live_server.steam.status_calls > status_calls

    activity = page.locator("#activity-log").inner_text()
    assert activity.index("Restart requested") < activity.index("Operator confirmed restart")
    assert activity.index("Operator confirmed restart") < activity.index("Restart completed (PID 3200)")
    assert INTERNAL_LOG_SENTINEL not in page.locator("body").inner_text()


def test_restart_failure_displays_error_and_reconciles_status(
    page: Page, live_server: BrowserTestServer
) -> None:
    live_server.steam.prepare_restart_failure()
    page.goto(f"{live_server.base_url}/steam")
    status_calls = live_server.steam.status_calls

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Restart in Big Picture").click()
    wait_until(live_server.steam.restart_started.is_set)
    expect(page.locator("#steam-state")).to_have_text("Restarting")

    live_server.steam.release_restart()
    expect(page.locator("#error-message")).to_contain_text("Test Steam launch failed.")
    expect(page.locator("#steam-state")).to_have_text("Running")
    expect(page.locator("#steam-pid")).to_have_text("2100")
    expect(page.locator("#activity-log")).to_contain_text("Restart failed: Test Steam launch failed.")
    assert live_server.steam.status_calls > status_calls
