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
    expect(page.get_by_role("button",name="Restart in Big Picture")).to_be_enabled()
    page.locator("#steam-control-token").fill("a"*32)
    page.locator("#steam-apply-token").click()
    page.once("dialog",lambda dialog:dialog.accept())
    page.get_by_role("button",name="Restart in Big Picture").click()
    expect(page.locator("#activity-log")).to_contain_text("Steam restart completed")
    assert sum(1 for op,_ in fake.received if op=="steam.lifecycle.restart")==1

def test_steam_offline_shows_unknown_not_stopped(page: Page, games_ui_server):
    base,fake=games_ui_server
    page.goto(base+"/steam")
    fake.set_steam(False)
    expect(page.locator("#steam-state")).to_have_text("Stopped")
    expect(page.get_by_role("button",name="Restart in Big Picture")).to_be_enabled()
