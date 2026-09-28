from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import BrowserTestServer


pytestmark = pytest.mark.only_browser("chromium")


def test_obs_management_page_apply_verify_activate_and_review(
    page: Page,
    live_server: BrowserTestServer,
) -> None:
    page.goto(f"{live_server.base_url}/")

    expect(page.get_by_role("heading", name="OBS Scene")).to_be_visible()
    expect(page.locator("#obs-card-status")).to_have_text("Connected")
    page.get_by_role("link", name="Manage OBS").click()

    expect(page).to_have_url(f"{live_server.base_url}/obs")
    expect(page.get_by_role("heading", name="Scene Profile Manager")).to_be_visible()
    expect(page.locator("#profile-list")).to_contain_text("Browser test profile")
    expect(page.locator("#profile-name")).to_have_value("Browser test profile")
    expect(page.locator("#editor-state")).to_have_text("Saved")

    page.locator("#profile-name").fill("Edited browser profile")
    expect(page.locator("#editor-state")).to_have_text("Modified")
    page.get_by_role("button", name="Add source").click()
    expect(page.locator("#source-list")).to_contain_text("browser_source")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#editor-state")).to_have_text("Saved")
    assert live_server.obs.profile["name"] == "Edited browser profile"

    page.get_by_role("button", name="Apply saved", exact=True).click()
    expect(page.locator("#activity-log")).to_contain_text("Apply: complete")
    assert live_server.obs.apply_calls == 1

    page.get_by_role("button", name="Verify", exact=True).click()
    expect(page.locator("#activity-log")).to_contain_text("Verify: PASS")
    assert live_server.obs.verify_calls >= 1

    page.get_by_role("button", name="Activate", exact=True).click()
    expect(page.locator("#activity-log")).to_contain_text("Activate: complete")
    assert live_server.obs.activate_calls == 1

    page.get_by_role("button", name="Review").click()
    expect(page.locator("#activity-log")).to_contain_text("Review queued: browser-review-1")
    expect(page.locator("#activity-log")).to_contain_text("Review completed: PASS")
    assert live_server.obs.review_calls == 1
    assert live_server.obs.review_status_calls >= 1
