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
    expect(page.get_by_role("heading", name="OBS Scene Management")).to_be_visible()
    expect(page.locator("#obs-state")).to_have_text("Connected")
    expect(page.locator("#obs-version")).to_have_text("32.0.2")
    expect(page.locator("#scene-result")).to_have_text("PASS")
    expect(page.locator("#source-list")).to_contain_text("StreamOps D4 Video")
    expect(page.locator("#source-list")).to_contain_text("StreamOps Voice")
    expect(page.locator("#source-list")).to_contain_text("signal required")
    expect(page.locator("#scene-preview")).to_be_visible()

    page.get_by_role("button", name="Apply", exact=True).click()
    expect(page.locator("#activity-log")).to_contain_text("Apply completed")
    assert live_server.obs.apply_calls == 1

    page.get_by_role("button", name="Verify", exact=True).click()
    expect(page.locator("#activity-log")).to_contain_text("Verify completed: PASS")
    assert live_server.obs.verify_calls >= 1

    page.get_by_role("button", name="Activate", exact=True).click()
    expect(page.locator("#activity-log")).to_contain_text("Activate completed")
    assert live_server.obs.activate_calls == 1

    page.get_by_role("button", name="Run 30s Review").click()
    expect(page.locator("#activity-log")).to_contain_text("Review queued: browser-review-1")
    expect(page.locator("#activity-log")).to_contain_text("Review completed")
    assert live_server.obs.review_calls == 1
    assert live_server.obs.review_status_calls >= 1
