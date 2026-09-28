from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import BrowserTestServer


pytestmark = pytest.mark.only_browser("chromium")


def test_capture_success_failure_and_latest_preview_retention(
    page: Page, live_server: BrowserTestServer
) -> None:
    page.goto(f"{live_server.base_url}/screen")
    button = page.get_by_role("button", name="Capture Screen")
    button.click()

    preview = page.locator("#preview")
    expect(preview).to_be_visible()
    expect(page.locator("#capture-resolution")).to_have_text("12 x 8")
    expect(page.locator("#activity-log")).to_contain_text("Capture requested")
    expect(page.locator("#activity-log")).to_contain_text("Capture completed 12x8")
    successful_src = preview.get_attribute("src")
    assert successful_src and successful_src.startswith("blob:")

    page.get_by_role("button", name="Capture Again").click()
    expect(page.locator("#error-message")).to_contain_text("Test capture failed.")
    expect(page.locator("#activity-log")).to_contain_text("Capture failed: Test capture failed.")
    expect(preview).to_be_visible()
    assert preview.get_attribute("src") == successful_src
