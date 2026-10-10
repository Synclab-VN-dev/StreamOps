"""Issue 86 ownership and WS-only conformance guard (independent of #85 code)."""
from pathlib import Path
import re
from streamops.server.app import WEB_ROOT

def read(name):
    return (WEB_ROOT / name).read_text(encoding="utf-8")

def test_game_manager_transport_is_ws_only():
    steam=read("steam.js")
    games=read("games.js")
    assert 'fetchJson(' not in steam
    assert 'fetchJson(' not in games
    assert "/api/v1/steam/status" not in steam
    assert "/api/v1/steam/restart" not in steam
    assert "fetch(" not in games
    assert "/api/v1/games/ws" in read("games-ws.js")
    assert "/api/v1/steam/ws" in read("steam-ws.js")
    assert "games.operations.get" in read("games-ws.js")
    assert "games.reconcile" in games
    assert "games.lifecycle.force_stop" not in games
    assert "unsafe.disabled=true" in read("games-components.js")
    assert "Force Stop (disabled)" in read("games-components.js")

def test_no_backend_or_demo_data_coupling():
    for name in ["games.js","games-store.js","games-ws.js","steam.js","games-components.js"]:
        source=read(name)
        assert "Diablo IV" not in source
        assert "2344520" not in source
        assert "scenario selector" not in source.lower()
        assert "localStorage" not in source
    command=read("games-control.js")
    assert "localStorage.setItem(" not in command and "localStorage.getItem(" not in command and "sessionStorage.setItem(" not in command
    assert "streamops-game-control." in command
    assert "sec-websocket-protocol" not in command.lower() # Native WS subprotocol only
    assert "new WebSocket(url," in command

def test_steam_summary_in_correct_location():
    html=read("steam.html")
    assert html.index('id="steam-status-panel"') < html.index('id="game-manager-card"') < html.index('id="activity-title"')
    assert 'href="/games"' in html
    assert 'src="/assets/games-ws.js"' in html
    assert 'src="/assets/steam-ws.js"' in html
    assert 'href="/assets/games.css"' in html

def test_gaming_detail_stays_in_two_pages_and_assets_exist():
    html=read("games.html")
    assert 'id="game-detail"' in html
    assert 'id="game-library"' in html
    assert 'id="game-search"' in html
    assert 'href="/steam"' in html
    assert 'src="/assets/games.js"' in html
    assert "Game Manager" in html
    assert "Mock" not in html
    for name in ["games.html","games.js","games.css","games-store.js","games-control.js","games-ws.js","steam-ws.js","games-components.js"]:
        assert (WEB_ROOT / name).is_file()
