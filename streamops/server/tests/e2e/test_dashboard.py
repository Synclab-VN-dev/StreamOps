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
    expect(page.get_by_role("heading", name="OBS")).to_be_visible()
    expect(page.get_by_role("heading", name="Activity Log")).to_be_visible()
    expect(page.locator("#status-text")).to_have_text("Online, capture unavailable")
    expect(page.locator("#screen-card-status")).to_have_text("Available")
    expect(page.locator("#steam-card-status")).to_have_text("Running")
    expect(page.locator("#obs-card-status")).to_have_text("READY")
    expect(page.locator("#activity-log")).to_contain_text("Page loaded")
    expect(page.locator("#activity-log")).to_contain_text("streamops-node: online")
    expect(page.locator("#activity-log")).to_contain_text("Steam status: running (PID 2100)")
    expect(page.locator("#activity-log")).to_contain_text("OBS status: READY (PID 5100)")

    page.get_by_role("link", name="Manage Steam").click()
    expect(page).to_have_url(f"{live_server.base_url}/steam")
    expect(page.get_by_role("heading", name="Steam Manager", exact=True)).to_be_visible()
    page.get_by_role("link", name="Dashboard").click()
    expect(page).to_have_url(f"{live_server.base_url}/")

    page.get_by_role("link", name="Open").click()
    expect(page).to_have_url(f"{live_server.base_url}/screen")
    expect(page.get_by_role("heading", name="Screen Capture")).to_be_visible()
    page.get_by_role("link", name="Dashboard").click()
    expect(page).to_have_url(f"{live_server.base_url}/")

    page.get_by_role("link", name="Manage OBS").click()
    expect(page).to_have_url(f"{live_server.base_url}/obs")
    expect(page.get_by_role("heading", name="OBS", exact=True)).to_be_visible()
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



def test_dashboard_coalesces_inflight_poll_without_missing_next_tick(
    page: Page, live_server: BrowserTestServer
) -> None:
    """A slow HTTP response cannot defer the next polling tick indefinitely.

    Deliberately hold one Steam read across two fixed 15-second clock ticks.
    The dashboard must not create overlapping requests and must run exactly
    one coalesced refresh once the slow request completes.
    """
    page.clock.install()
    page.goto(f"{live_server.base_url}/")
    expect(page.locator("#steam-card-status")).to_have_text("Running")

    page.evaluate("""() => {
      const original = window.StreamOpsUI.fetchJson;
      const probe = {calls:0, active:0, maxActive:0, release:null};
      window.__dashboardPollProbe = probe;
      window.StreamOpsUI.fetchJson = async (url, options) => {
        if (url !== '/api/v1/steam/status') return original(url, options);
        probe.calls++;
        probe.active++;
        probe.maxActive = Math.max(probe.maxActive, probe.active);
        try {
          if (probe.calls === 1) {
            await new Promise(resolve => { probe.release = resolve; });
          }
          return await original(url, options);
        } finally {
          probe.active--;
        }
      };
    }""")

    page.clock.fast_forward(15_000)
    page.wait_for_function(
        "window.__dashboardPollProbe.calls === 1 && "
        "typeof window.__dashboardPollProbe.release === 'function'"
    )
    page.clock.fast_forward(15_000)
    assert page.evaluate("window.__dashboardPollProbe.calls") == 1, (
        "In-flight HTTP polling must not overlap"
    )

    page.evaluate("window.__dashboardPollProbe.release()")
    page.wait_for_function(
        "window.__dashboardPollProbe.calls === 2 && "
        "window.__dashboardPollProbe.active === 0"
    )
    assert page.evaluate("window.__dashboardPollProbe.maxActive") == 1
    expect(page.locator("#steam-card-status")).to_have_text("Running")
    assert page.locator("#activity-log").inner_text().count(
        "Steam status: running"
    ) == 1, "Coalesced polls must not create duplicate Activity Log entries"
