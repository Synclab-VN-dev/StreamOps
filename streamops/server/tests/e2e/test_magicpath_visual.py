"""FE-G5 — real cross-viewport visual comparison to PINNED MagicPath source.

Original MagicPath reference code/preview blobs are immutable and validated by
test_magicpath_visual_contract. The generated reference screenshots are NOT
silently accepted as user-approved goldens. Approval is an explicit CI gate.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
from PIL import Image, ImageChops, ImageEnhance, ImageStat
import pytest
from playwright.sync_api import Browser, expect

from .test_games_ui import games_ui_server, game

ROOT = Path(__file__).resolve().parents[1] / "visual_magicpath"
SOURCE = ROOT / "reference_source"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
OUT = Path(os.getenv("STREAMOPS_VISUAL_ARTIFACTS", str(ROOT / "_artifacts")))
REQUIRED_SCENARIOS = (
    [("steam", "normal", 360, 800), ("games", "default", 360, 800)]
    + [(design, "normal" if design == "steam" else "default", width, height)
       for design in ("steam", "games") for width, height
       in ((390,844), (768,1024), (1440,900))]
    + [("steam", s, 390, 844) for s in ("empty", "multi", "offline", "error")]
    + [("games", s, 390, 844) for s in ("multi", "empty", "offline", "loading", "stopTimeout")]
    + [("games", "detail", 390, 844), ("games", "detail", 1440, 900)]
)

pytestmark = [pytest.mark.only_browser("chromium"),
    pytest.mark.skipif(os.getenv("STREAMOPS_VISUAL_ENFORCE_APPROVAL") != "1",
        reason="Runs in required dedicated FE-G5 after pinned reference renderer install")]


@pytest.fixture(scope="module")
def magicpath_reference_url():
    """Start the isolated original MagicPath React+Tailwind source, no FE import."""
    port = 5178
    process = subprocess.Popen(
        ["npm.cmd" if os.name == "nt" else "npm", "run", "start"],
        cwd=SOURCE, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        env={**os.environ, "CI": "1"},
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            if process.poll() is not None:
                raise RuntimeError("Pinned MagicPath Vite server exited early")
            try:
                with urllib.request.urlopen(url + "/?design=steam", timeout=1) as r:
                    if r.status == 200: break
            except OSError:
                time.sleep(.2)
        else:
            raise TimeoutError("MagicPath reference server not ready")
        yield url
    finally:
        process.terminate()
        try: process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _ready(page):
    # Disable motion only, preserve original design geometry.
    page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;}")
    page.evaluate("() => document.fonts.ready")
    page.wait_for_timeout(120)


def _stage_production(page, fake, base, design, scenario):
    page.goto(base + ("/steam" if design == "steam" else "/games"))
    if design == "steam":
        expect(page.locator("#steam-state")).not_to_have_text("Checking")
        if scenario == "empty":
            fake.set_library([])
        elif scenario == "multi":
            fake.set_library([game("Diablo IV", "steam:2344520"), game("Other", "steam:111"),
                              game("Third", "steam:222")])
        elif scenario in ("offline", "error"):
            page.evaluate("() => { window.StreamOpsSteam.destroy(); window.StreamOpsGames.client.destroy(); }")
            expect(page.locator("#steam-state")).to_have_text("UNKNOWN")
    else:
        expect(page.locator("#game-library button")).to_have_count(1)
        if scenario == "empty":
            fake.set_library([])
            expect(page.locator("#game-library")).to_contain_text("No matching games")
        elif scenario == "multi":
            fake.set_library([game("Diablo IV", "steam:2344520"),
                              game("Hollow Knight", "steam:234"), game("Hades II", "steam:345")])
            expect(page.locator("#game-library button")).to_have_count(3)
        elif scenario == "offline":
            page.evaluate("() => window.StreamOpsGames.client.destroy()")
            expect(page.locator("#status-text")).to_contain_text("offline")
        elif scenario == "loading":
            page.evaluate("() => { const s=window.StreamOpsGames.store; s.reset(); s.connected=true; s.loading=true; s.stale=true; s.emit(); }")
        elif scenario == "stopTimeout":
            page.locator("#game-library button").first.click()
            page.evaluate("""() => {
              const store=window.StreamOpsGames.store;
              store.operation({operation_id:'visual-op',game_id:'steam:2344520',
                 action:'stop',status:'UNKNOWN',phase:'TIMEOUT',code:'timeout'});
            }""")
        elif scenario == "detail":
            page.locator("#game-library button").first.click()
            expect(page.locator("#game-detail")).to_contain_text("Diablo IV")


def _stage_reference(page, url, design, scenario):
    page.goto(url + "?design=" + design)
    target = scenario if scenario != "detail" else "default"
    page.locator('select[aria-label="Design scenario"]').select_option(target)
    if scenario == "detail":
        # Open the very first game's panel in the original MagicPath design.
        page.get_by_role("button", name="Diablo IV").first.click()
        expect(page.get_by_role("complementary", name="Game details")).to_be_visible()


def _visual_diff(expected_path, actual_path, diff_path):
    with Image.open(expected_path) as e, Image.open(actual_path) as a:
        exp=e.convert("RGB"); act=a.convert("RGB")
        if exp.size != act.size:
            raise AssertionError(f"Viewport dimensions differ: {exp.size} vs {act.size}")
        diff=ImageChops.difference(exp, act)
        score=sum(ImageStat.Stat(diff).mean)/(255.0*3)
        ImageEnhance.Contrast(diff).enhance(4).save(diff_path)
        return round(score, 5)


@pytest.mark.parametrize("design,scenario,width,height", REQUIRED_SCENARIOS)
def test_pinned_magicpath_visual_parity(
    browser: Browser, games_ui_server, magicpath_reference_url,
    design: str, scenario: str, width: int, height: int,
):
    base, fake = games_ui_server
    label=f"{design}-{scenario}-{width}x{height}"
    path=OUT / label
    path.mkdir(parents=True, exist_ok=True)
    expected=path/"expected-magicpath.png"
    actual=path/"actual-streamops.png"
    diff=path/"diff.png"
    expected_page=browser.new_page(viewport={"width":width,"height":height},device_scale_factor=1)
    actual_page=browser.new_page(viewport={"width":width,"height":height},device_scale_factor=1)
    try:
        # Original reference and product are NEVER the same server or codebase.
        _stage_reference(expected_page, magicpath_reference_url, design, scenario)
        _ready(expected_page)
        expected_page.screenshot(path=str(expected), animations="disabled")
        if MANIFEST["approved"]:
            approved = ROOT / "goldens" / (label + ".png")
            assert approved.is_file(), "Missing owner-approved Golden " + str(approved)
            expected_hash = MANIFEST["approval"]["expected_sha256"].get(label)
            assert expected_hash and hashlib.sha256(approved.read_bytes()).hexdigest() == expected_hash, "Golden hash mismatch"
            drift=_visual_diff(approved,expected,path/"reference-drift.png")
            assert drift <= .015, f"Pinned design renderer drift against approved Golden: {label}: {drift}"
        _stage_production(actual_page, fake, base, design, scenario)
        _ready(actual_page)
        actual_page.screenshot(path=str(actual), animations="disabled")
        verified_reference=ROOT / "goldens" / (label + ".png") if MANIFEST["approved"] else expected
        score=_visual_diff(verified_reference,actual,diff)
        (path/"result.json").write_text(json.dumps({
            "design":design, "scenario":scenario, "viewport":[width,height],
            "revision_id":next(r["revision_id"] for r in MANIFEST["references"] if r["name"]==design),
            "difference_mean_rgb":score, "owner_approved":MANIFEST["approved"],
            "reference_source":"original MagicPath revision source, NOT production UI",
            "artifacts":["expected-magicpath.png","actual-streamops.png","diff.png"],
        },indent=2),encoding="utf-8")
        # Strict threshold; never relax it automatically to make red CI green.
        assert score <= .08, f"{label}: visual diff mean={score:.3f}, allowed=.08; see diff artifact"
    finally:
        expected_page.close();actual_page.close()


def test_owner_approval_is_required_for_visual_golden():
    # When enabled in CI, missing owner review is a BLOCKER, not a SKIP.
    if os.getenv("STREAMOPS_VISUAL_ENFORCE_APPROVAL") == "1":
        assert MANIFEST["approved"] is True, "Golden not yet approved by project owner. Review CI expected/actual/diff artifacts."
        assert MANIFEST["approval"]["approved_by"]
        assert MANIFEST["approval"]["approved_at"]
        assert MANIFEST["approval"]["review_url"]
        assert len(MANIFEST["approval"]["expected_sha256"]) == len(REQUIRED_SCENARIOS)
