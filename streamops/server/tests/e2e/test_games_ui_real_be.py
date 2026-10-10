"""Real FE→WS→GameService/SteamService integration: only on combined #85+#86 branch.
Run only with the genuine #85 backend; the independent FE branch uses FakeContract.
"""
from __future__ import annotations
import pytest
from playwright.sync_api import Page, expect
from .conftest import BrowserTestServer

pytestmark = pytest.mark.only_browser("chromium")

def test_real_game_ws_browser_consumer_and_steam_ws(page: Page, live_server: BrowserTestServer):
    api_calls = []
    errors = []
    page.on("request", lambda req: api_calls.append(req.url)
            if "/api/v1/games" in req.url or "/api/v1/steam/" in req.url else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(live_server.base_url + "/steam")
    expect(page.locator("#steam-pid")).to_have_text("2100", timeout=10000)
    expect(page.locator("#games-connection")).to_have_text("LIVE", timeout=15000)
    expect(page.locator("#steam-games-summary")).to_contain_text("Registered")
    # The backend static catalog exposes the canonical Diablo IV identity.
    # Absence of installed/verified process must NEVER become a fake RUNNING state.
    page.goto(live_server.base_url + "/games")
    expect(page.locator("#status-text")).to_contain_text("connected", timeout=15000)
    expect(page.locator("#game-library")).to_contain_text("Diablo IV", timeout=15000)
    page.locator("#game-library button").first.click()
    expect(page.locator("#game-detail")).to_contain_text("OBS capture")
    expect(page.locator("#game-detail")).to_contain_text("Windows session")
    expect(page.get_by_role("button", name="Force Stop (disabled)")).to_be_disabled()
    assert not errors, errors
    # Websocket upgrade is separate from HTTP REST polling.
    assert not [url for url in api_calls if (
        "/api/v1/steam/status" in url or "/api/v1/steam/restart" in url
        or "/api/v1/games" in url and "/ws" not in url
    )], api_calls
