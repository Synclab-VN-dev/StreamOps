"""Steam WebUI regression for #86 uses WS fixture; SteamService REST is tested separately."""
from __future__ import annotations
import pytest
from playwright.sync_api import Page, expect
from .test_games_ui import games_ui_server

pytestmark=pytest.mark.only_browser("chromium")

def test_steam_process_status_and_restart_ws(page: Page, games_ui_server):
    base,fake=games_ui_server
    page.goto(base+"/steam")
    expect(page.locator("#steam-state")).to_have_text("Running")
    expect(page.locator("#steam-pid")).to_have_text("7777")
    expect(page.locator("#steam-uptime")).to_have_text("01:02:03")
    expect(page.locator("#steam-session")).to_have_text("1")
    expect(page.locator("#steam-interactive")).to_have_text("Yes")
    page.locator("#steam-runtime-details summary").click()
    expect(page.locator("#steam-session-expanded")).to_have_text("1")
    expect(page.get_by_role("button",name="Restart in Big Picture")).to_be_enabled()
    # BE #85 accepts the versioned Steam WS on the trusted LAN without
    # application tokens. The product must not block Restart on token input.
    expect(page.locator("#steam-control-token")).to_have_count(0)
    expect(page.locator(".gm-control-panel")).to_have_count(0)
    page.get_by_role("button",name="Restart in Big Picture").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.locator(".gm-confirm-accept").click()
    expect(page.locator("#activity-log")).to_contain_text("Steam restart completed")
    assert sum(1 for op,_ in fake.received if op=="steam.lifecycle.restart")==1

def test_steam_offline_shows_unknown_not_stopped(page: Page, games_ui_server):
    base,fake=games_ui_server
    page.goto(base+"/steam")
    fake.set_steam(False)
    expect(page.locator("#steam-state")).to_have_text("Stopped")
    page.locator("#steam-runtime-details summary").click()
    expect(page.get_by_role("button",name="Restart in Big Picture")).to_be_enabled()
