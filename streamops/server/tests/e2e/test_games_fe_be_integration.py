"""#86: Playwright UI against the REAL #85 FastAPI GameService/WebSocket.

Synthetic Windows process and Steam backends only: never launch/stop real games.
This deliberately does not use FE's FakeContract WebSocket fixture.
"""
from __future__ import annotations

import socket
import threading

import pytest
import uvicorn
from playwright.sync_api import Browser, expect

from streamops.server.app import create_app
from streamops.server.services import SteamService
from streamops.server.tests.test_games_lifecycle import GAME, build_service
from streamops.server.tests.test_steam import FakeSteamBackend, RUNNING, STOPPED
from .conftest import wait_until


pytestmark = pytest.mark.only_browser("chromium")


@pytest.fixture
def integrated_game_ui_server(server_config, capture_service, tmp_path):
    service, platform = build_service(tmp_path, interval=0.025)
    steam = FakeSteamBackend(status=RUNNING)
    app = create_app(
        server_config, capture_service=capture_service,
        steam_service=SteamService(steam), game_service=service,
        manage_runtime=False,
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning",
        lifespan="on", timeout_graceful_shutdown=3,
    ))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True,
    )
    thread.start()
    wait_until(lambda: server.started, timeout=15)
    try:
        yield f"http://127.0.0.1:{port}", platform, steam
    finally:
        server.should_exit = True
        thread.join(timeout=12)
        listener.close()
        assert not thread.is_alive(), "Real BE test server did not shut down"


def test_real_game_service_external_status_pushes_to_steam_and_games(
        browser: Browser, integrated_game_ui_server):
    """Real WS hub → independent browser observers; zero game status REST polling."""
    base, platform, steam = integrated_game_ui_server
    first = browser.new_page()
    second = browser.new_page()
    requests = []
    for page in (first, second):
        page.on("request", lambda req: requests.append(req.url)
                if "/api/v1/" in req.url and req.resource_type != "websocket" else None)
    try:
        first.goto(base + "/steam")
        second.goto(base + "/games")
        expect(first.locator("#steam-state")).to_have_text("Running")
        expect(first.locator("#games-connection")).to_contain_text("0 running")
        expect(second.locator("#game-library .gm-game-row")).to_have_count(1)
        second.locator(f'#game-library .gm-game-row[data-game-id="{GAME}"]').click()
        expect(second.locator("#game-detail")).to_contain_text("Stopped")

        # BE observer notices synthetic external process change without a
        # WebUI refresh, REST status call or lifecycle command.
        platform.running = True
        expect(first.locator("#games-connection")).to_contain_text("1 running", timeout=15000)
        expect(second.locator("#game-detail")).to_contain_text("Running", timeout=15000)
        expect(first.locator("#steam-running-games .gm-game-row")).to_have_count(1)
        assert second.evaluate("window.StreamOpsGames.store.revision > 0")
        platform.running = False
        expect(first.locator("#games-connection")).to_contain_text("0 running", timeout=15000)
        expect(second.locator("#game-detail")).to_contain_text("Stopped", timeout=15000)
        assert not requests, f"Real WebUI must not fall back to REST: {requests}"
        assert platform.start_calls == platform.stop_calls == steam.restart_calls == 0
    finally:
        first.close()
        second.close()


def test_real_game_service_confirmed_start_and_reconcile_over_ws(
        browser: Browser, integrated_game_ui_server):
    """FE command + REAL #85 WS + synthetic action verification and confirmation."""
    base, platform, steam = integrated_game_ui_server
    page = browser.new_page()
    try:
        page.goto(base + "/games")
        expect(page.locator("#game-library .gm-game-row")).to_have_count(1)
        page.locator(f'#game-library .gm-game-row[data-game-id="{GAME}"]').click()
        start = page.locator('#game-detail button[data-action="start"]')
        expect(start).to_be_enabled()
        page.once("dialog", lambda dialog: dialog.dismiss())
        start.click()
        assert platform.start_calls == 0, "Canceled confirmation MUST NOT mutate process"
        page.once("dialog", lambda dialog: dialog.accept())
        start.click()
        expect(page.locator("#game-detail")).to_contain_text("Running", timeout=15000)
        expect(page.locator("#game-detail .gm-operation")).to_contain_text(
            "SUCCEEDED", timeout=15000,
        )
        assert platform.start_calls == 1 and platform.stop_calls == 0
        assert steam.restart_calls == 0
        page.locator("#game-detail .gm-detail-refresh").click()
        expect(page.locator("#game-detail")).to_contain_text("Running", timeout=15000)
        assert platform.start_calls == 1 and platform.stop_calls == 0
    finally:
        page.close()



def test_real_steam_ws_push_and_restart_confirmation_without_rest(
        browser: Browser, integrated_game_ui_server):
    """E2E-06: real merged Steam WS pushes status, restart is opt-in, zero REST polling."""
    base, platform, steam = integrated_game_ui_server
    page = browser.new_page()
    requests = []
    page.on("request", lambda req: requests.append(req.url)
            if "/api/v1/" in req.url and req.resource_type != "websocket" else None)
    try:
        page.goto(base + "/steam")
        expect(page.locator("#steam-state")).to_have_text("Running")
        expect(page.locator("#status-text")).to_have_text("Steam WS connected")
        page.locator("#steam-runtime-details summary").click()
        expect(page.locator("#node-health-status")).to_contain_text(
            "Node health: online · Capture READY", timeout=15000,
        )
        steam.status_result = STOPPED
        expect(page.locator("#steam-state")).to_have_text("Stopped", timeout=15000)
        steam.status_result = RUNNING
        expect(page.locator("#steam-state")).to_have_text("Running", timeout=15000)
        button = page.locator("#restart-button")
        expect(button).to_be_enabled()
        page.once("dialog", lambda d: d.dismiss())
        button.click()
        assert steam.restart_calls == 0, "Canceled restart must not call real SteamService"
        page.once("dialog", lambda d: d.accept())
        button.click()
        expect(page.locator("#activity-log")).to_contain_text(
            "Steam restart completed", timeout=15000,
        )
        assert steam.restart_calls == 1
        assert platform.start_calls == platform.stop_calls == 0
        assert not requests, f"Steam frontend used REST instead of WS: {requests}"
    finally:
        page.close()
