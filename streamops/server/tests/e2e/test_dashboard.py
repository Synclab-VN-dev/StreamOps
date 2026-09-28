from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import BrowserTestServer, wait_until


pytestmark = pytest.mark.only_browser("chromium")


def test_dashboard_cards_activity_and_navigation(
    page: Page, live_server: BrowserTestServer
) -> None:
    page.goto(f"{live_server.base_url}/")

    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(page.get_by_role("heading", name="Screen Capture")).to_be_visible()
    expect(page.get_by_role("heading", name="Steam")).to_be_visible()
    expect(page.get_by_role("heading", name="Activity Log")).to_be_visible()
    expect(page.locator("#status-text")).to_have_text("Online, capture unavailable")
    expect(page.locator("#screen-card-status")).to_have_text("Available")
    expect(page.locator("#steam-card-status")).to_have_text("Running")
    expect(page.locator("#activity-log")).to_contain_text("Page loaded")
    expect(page.locator("#activity-log")).to_contain_text("streamops-node: online")
    expect(page.locator("#activity-log")).to_contain_text("Steam status: running (PID 2100)")

    page.get_by_role("link", name="Manage Steam").click()
    expect(page).to_have_url(f"{live_server.base_url}/steam")
    expect(page.get_by_role("heading", name="Steam", exact=True)).to_be_visible()
    page.get_by_role("link", name="Dashboard").click()
    expect(page).to_have_url(f"{live_server.base_url}/")

    page.get_by_role("link", name="Open").click()
    expect(page).to_have_url(f"{live_server.base_url}/screen")
    expect(page.get_by_role("heading", name="Screen Capture")).to_be_visible()
    page.get_by_role("link", name="Dashboard").click()
    expect(page).to_have_url(f"{live_server.base_url}/")


def test_dashboard_logs_state_changes_without_poll_duplicates(
    page: Page, live_server: BrowserTestServer
) -> None:
    page.clock.install()
    page.goto(f"{live_server.base_url}/")
    expect(page.locator("#steam-card-status")).to_have_text("Running")
    initial_entries = page.locator("#activity-log .activity-entry")
    initial_count = initial_entries.count()
    initial_status_calls = live_server.steam.status_calls

    live_server.steam.set_stopped()
    page.clock.fast_forward(15_000)
    wait_until(lambda: live_server.steam.status_calls > initial_status_calls)
    expect(page.locator("#steam-card-status")).to_have_text("Stopped")
    expect(page.locator("#activity-log")).to_contain_text("Steam status: stopped")
    changed_count = initial_entries.count()
    assert changed_count == initial_count + 1

    status_calls = live_server.steam.status_calls
    page.clock.fast_forward(15_000)
    wait_until(lambda: live_server.steam.status_calls > status_calls)
    assert initial_entries.count() == changed_count

    capture_response = page.request.post(f"{live_server.base_url}/api/v1/screen/capture")
    assert capture_response.ok
    status_calls = live_server.steam.status_calls
    page.clock.fast_forward(15_000)
    wait_until(lambda: live_server.steam.status_calls > status_calls)
    expect(page.locator("#status-text")).to_have_text("Online")
    expect(page.locator("#activity-log")).to_contain_text(
        "streamops-node: online, capture ready via fake-browser"
    )

    live_server.steam.set_running(4100)
    status_calls = live_server.steam.status_calls
    page.clock.fast_forward(15_000)
    wait_until(lambda: live_server.steam.status_calls > status_calls)
    expect(page.locator("#steam-card-detail")).to_contain_text("PID 4100")
    expect(page.locator("#activity-log")).to_contain_text("Steam status: running (PID 4100)")
