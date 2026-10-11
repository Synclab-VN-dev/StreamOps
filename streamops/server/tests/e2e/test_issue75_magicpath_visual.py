"""Issue #75 FE-G5: actual FE vs original, PINNED MagicPath reference.

This is intentionally fail-closed while owner-approved goldens / design states
are absent. Never accept a production screenshot as a design baseline.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from PIL import Image,ImageChops,ImageEnhance,ImageStat
import pytest
from playwright.sync_api import Browser,expect

from .test_issue75_workflow_matrix import ScenarioWS
from .conftest import BrowserTestServer
from ..test_issue75_magicpath_visual_contract import (
    ROOT,read_bytes,load,validate_approval,validate_source
)

MANIFEST=load()
ARTIFACTS=Path(os.environ.get(
    "STREAMOPS_OBS_VISUAL_ARTIFACTS",str(ROOT/"_artifacts")
))
pytestmark=[
    pytest.mark.only_browser("chromium"),
    pytest.mark.skipif(os.getenv("STREAMOPS_OBS_VISUAL_ENFORCE")!="1",
        reason="This suite runs in the dedicated mandatory FE-G5 workflow"),
]

@pytest.fixture(scope="module")
def original_magicpath_url():
    renderer=ROOT/"reference_source"
    executable="npm.cmd" if os.name=="nt" else "npm"
    proc=subprocess.Popen(
        [executable,"run","start"],
        cwd=renderer,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        env={**os.environ,"CI":"1"},
    )
    url="http://127.0.0.1:5179"
    try:
        for _ in range(160):
            if proc.poll() is not None:
                raise RuntimeError("Original MagicPath renderer build/start failed")
            try:
                with urllib.request.urlopen(url+"/?design=plugin",timeout=1) as response:
                    if response.status==200:
                        break
            except OSError:
                time.sleep(.2)
        else:
            raise TimeoutError("Pinned MagicPath renderer unavailable")
        yield url
    finally:
        proc.terminate()
        try:proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

def stable(page):
    page.add_style_tag(content=(
        "*,*::before,*::after{animation:none!important;"
        "transition:none!important;caret-color:transparent!important}"
    ))
    page.evaluate("() => document.fonts.ready")
    page.wait_for_timeout(120)

def position(page,case,reference):
    if case["capture"]=="scroll":
        page.evaluate("() => window.scrollTo(0,480)")
    elif case["capture"]=="card":
        if reference:
            page.get_by_role("heading",name="Plugin Manager",exact=True).scroll_into_view_if_needed()
        else:
            page.locator("#plugin-manager-dashboard-card").scroll_into_view_if_needed()
    page.wait_for_timeout(80)

def stage_reference(page,url,case):
    page.goto(url+"/?design="+case["design"])
    if case["design"]=="plugin":
        expect(page.get_by_role("heading",name="OBS Plugin Manager")).to_be_visible()
        if case["state"]=="confirm":
            reference_scroll=page.evaluate("window.scrollY")
            page.get_by_role("button",name="Install plugin",exact=True).click()
            native_modal=page.get_by_role("dialog")
            expect(native_modal).to_be_visible()
            expect(native_modal.get_by_role("heading",name="Install plugin?")).to_be_visible()
            assert native_modal.evaluate("el => el.matches(':modal')"), (
                "Pinned MagicPath Confirm must open a native top-layer popup"
            )
            assert page.evaluate("window.scrollY")==reference_scroll, (
                "Confirm must overlay rather than shift the original page"
            )
    else:
        expect(page.get_by_role("heading",name="Plugin Manager",exact=True)).to_be_visible()
    stable(page)
    position(page,case,True)

def stage_product(page,server,case):
    # Browser fixture is BE-v2 shaped; no production mock images, REST fallback,
    # fake releases, or filesystem/OBS mutations.
    fake=ScenarioWS(page,plugin_state="NOT_INSTALLED",
                    installed_version=None,obs_state="STOPPED")
    page.goto(server.base_url+("/obs" if case["design"]=="dashboard" else "/obs/plugins"))
    if case["design"]=="plugin":
        expect(page.locator("#plugin-managed-count")).to_have_text("1")
        # The approved reference expands the first plugin on initial load.
        expect(page.locator(".plugin-card-header")).to_have_attribute("aria-expanded","true")
        if case["state"]=="confirm":
            page.get_by_role("button",name="Install plugin",exact=True).click()
            modal=page.locator("#plugin-confirm-dialog")
            expect(modal).to_be_visible()
            assert modal.evaluate("el => el.matches(':modal')"), (
                "Product Confirm must remain a native modal, not an inline panel"
            )
    else:
        expect(page.locator("#plugin-dashboard-managed")).to_have_text("1")
    stable(page)
    position(page,case,False)
    assert fake.mutations()==[],"Visual comparison must not mutate OBS/plugins"
    return fake

def pixel_difference(expected,actual,out):
    with Image.open(expected) as e,Image.open(actual) as a:
        exp=e.convert("RGB")
        act=a.convert("RGB")
        assert exp.size==act.size,f"Geometry mismatch {exp.size} != {act.size}"
        diff=ImageChops.difference(exp,act)
        score=sum(ImageStat.Stat(diff).mean)/(255.0*3)
        ImageEnhance.Contrast(diff).enhance(4).save(out)
        return round(score,5)

@pytest.mark.parametrize(
    "case",MANIFEST["required_cases"],
    ids=lambda case:case["label"],
)
def test_original_magicpath_to_live_fe_visual(
    browser:Browser,live_server:BrowserTestServer,original_magicpath_url,case
):
    validate_source(MANIFEST)
    folder=ARTIFACTS/case["label"]
    folder.mkdir(parents=True,exist_ok=True)
    expected=folder/"expected-magicpath.png"
    actual=folder/"actual-streamops.png"
    difference=folder/"diff.png"
    viewport={"width":case["width"],"height":case["height"]}
    ref_page=browser.new_page(viewport=viewport,device_scale_factor=1)
    fe_page=browser.new_page(viewport=viewport,device_scale_factor=1)
    try:
        stage_reference(ref_page,original_magicpath_url,case)
        ref_page.screenshot(path=str(expected),animations="disabled")
        stage_product(fe_page,live_server,case)
        fe_page.screenshot(path=str(actual),animations="disabled")
        score=pixel_difference(expected,actual,difference)
        reference_design=next(x for x in MANIFEST["references"] if x["kind"]==case["design"])
        report={
            "case":case,"magicpath_component_id":reference_design["component_id"],
            "magicpath_revision_id":reference_design["revision_id"],
            "git_head":os.environ.get("GITHUB_SHA","local"),
            "approved":MANIFEST["approved"],
            "candidate":not MANIFEST["approved"],
            "difference_mean_rgb":score,
            "threshold":MANIFEST["rendering"]["mean_rgb_limit"],
            "capture_scroll_y":{
                "reference":ref_page.evaluate("window.scrollY"),
                "actual":fe_page.evaluate("window.scrollY")},
            "artifacts":[expected.name,actual.name,difference.name],
        }
        (folder/"result.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        if MANIFEST["approved"]:
            validate_approval(MANIFEST)
            golden=ROOT/"goldens"/(case["label"]+".png")
            reference_drift=pixel_difference(golden,expected,folder/"reference-drift.png")
            assert reference_drift<=MANIFEST["rendering"]["reference_drift_limit"],(
                f'Original MagicPath renderer drift: {case["label"]}={reference_drift}'
            )
            product_score=pixel_difference(golden,actual,folder/"approved-golden-diff.png")
            assert product_score<=MANIFEST["rendering"]["mean_rgb_limit"],(
                f'Visual UI drift: {case["label"]}={product_score}; see diff artifact'
            )
        # Candidate renders also MUST reject an actual FE/design mismatch.
        # Otherwise the CI might report nine green visual tests while real UI
        # exceeds the fixed pixel threshold and only owner approval is red.
        assert score<=MANIFEST["rendering"]["mean_rgb_limit"],(
            f'Pinned MagicPath vs FE visual diff: {case["label"]}={score}; '
            'see expected/actual/diff in CI artifact. Fix FE or get revised design.'
        )
    finally:
        ref_page.close()
        fe_page.close()

def test_magicpath_golden_owner_approval_is_mandatory():
    # Placed after parameterized captures so CI uploads REVIEW CANDIDATES
    # even when the manifest is not yet explicitly approved by the owner.
    validate_source(MANIFEST)
    validate_approval(MANIFEST)
