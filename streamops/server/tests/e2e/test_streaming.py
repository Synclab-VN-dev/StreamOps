from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.only_browser("chromium")


def open_card(page, selector: str) -> None:
    page.locator(selector).evaluate("el => el.open = true")


def applied_profile(server, name: str = "Streaming Profile"):
    profile = server.obs.create_profile({"name": name})
    server.obs.apply_profile(profile["id"])
    server.obs.activate_profile(profile["id"])
    verified = server.obs.verify_profile(profile["id"], runtime=True)
    assert verified.status == "PASS"
    return profile


def test_obs_streaming_card_matches_mobile_design_contract(page, live_server):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(live_server.base_url + "/obs")
    expect(page.locator("#streaming-state-pill")).to_have_text("IDLE", timeout=7000)

    card = page.locator("#streaming-card")
    assert card.evaluate("el => el.open") is False
    expect(card.locator(".card-title-row p")).to_have_text(
        "Destinations, preflight and live output"
    )

    open_card(page, "#streaming-card")
    panel = card.locator(".streaming-overview-panel")
    expect(panel).to_be_visible()
    assert panel.locator(":scope > div").count() == 4

    panel_style = panel.evaluate(
        "el => ({ backgroundColor: getComputedStyle(el).backgroundColor, "
        "borderRadius: getComputedStyle(el).borderRadius })"
    )
    assert panel_style["backgroundColor"] == "rgb(250, 250, 250)"
    assert float(panel_style["borderRadius"].removesuffix("px")) >= 16

    cta = page.locator("#open-streaming")
    expect(cta).to_be_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def install_v2_routes(page, profile, *, preflight_status="PASS"):
    state = {
        "preflight_status": preflight_status,
        "destinations": [],
        "requests": [],
        "credential_bodies": [],
    }

    def obs_status(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"state": "READY"}),
        )

    def profiles(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"profiles": [profile]}),
        )

    def preflight(route):
        payload = route.request.post_data_json
        state["requests"].append(("preflight", payload))
        checks = [
            {"id": "obs_ready", "status": "PASS", "message": "OBS ready"},
            {
                "id": "profile_verify",
                "status": state["preflight_status"],
                "message": "Profile verified" if state["preflight_status"] == "PASS" else "Profile mismatch",
            },
        ]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": state["preflight_status"],
                    "profile_id": payload["profile_id"],
                    "checks": checks,
                }
            ),
        )

    def multistream(route):
        request = route.request
        url = request.url
        method = request.method
        suffix = url.split("/api/v1/multistream", 1)[1]
        state["requests"].append((method, suffix))

        if suffix == "/destinations" and method == "GET":
            body = {"destinations": state["destinations"]}
        elif suffix == "/destinations" and method == "POST":
            payload = request.post_data_json
            state["credential_bodies"].append(payload.copy())
            destination = {
                "destination_id": payload["destination_id"],
                "name": payload["name"],
                "server_url": payload["server_url"],
                "enabled": payload.get("enabled", True),
                "state": "IDLE",
            }
            state["destinations"].append(destination)
            body = destination
        elif suffix.endswith("/start") and method == "POST":
            destination = state["destinations"][0]
            destination["state"] = "STARTING"
            body = destination
        elif suffix.endswith("/stop") and method == "POST":
            destination = state["destinations"][0]
            destination["state"] = "STOPPING"
            body = destination
        else:
            route.fulfill(status=404, content_type="application/json", body="{}")
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/api/v1/obs/process/status", obs_status)
    page.route("**/api/v1/scene-profiles", profiles)
    page.route("**/api/v1/live/preflight/shared", preflight)
    page.route("**/api/v1/multistream/destinations**", multistream)
    return state


def add_destination_v2(page, *, secret="browser-stream-secret"):
    page.locator("#add-destination").click()
    page.locator("#destination-name").fill("LAN Test")
    page.locator("#destination-url").fill("rtmp://127.0.0.1:1935/live")
    page.locator("#destination-credential").fill(secret)
    page.locator("#editor-save").click()
    expect(page.locator(".v2-destination")).to_have_count(1)
    expect(page.locator("#destination-credential")).to_have_value("")
    expect(page.locator("body")).not_to_contain_text(secret)


def test_stream_manager_v2_loads_profile_and_is_mobile_safe(page, live_server):
    profile = applied_profile(live_server)
    state = install_v2_routes(page, profile)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(live_server.base_url + "/obs/stream")

    expect(page.locator("#obs-state")).to_have_text("READY", timeout=7000)
    expect(page.locator("#preflight-profile")).to_have_value(profile["id"])
    expect(page.locator("#preflight-pill")).to_have_text("NOT RUN")
    expect(page.locator("#destination-empty")).to_be_visible()
    assert state["destinations"] == []
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_stream_manager_v2_preflight_fail_blocks_start(page, live_server):
    profile = applied_profile(live_server)
    state = install_v2_routes(page, profile, preflight_status="FAIL")
    page.goto(live_server.base_url + "/obs/stream")
    add_destination_v2(page, secret="fail-secret")

    page.locator("#run-preflight").click()
    expect(page.locator("#preflight-pill")).to_contain_text("FAILED")
    page.locator(".v2-destination-head").click()
    expect(page.locator('[data-action="start"]')).to_be_disabled()
    assert not any(req == ("POST", "/destinations/lan-test/start") for req in state["requests"])
    expect(page.locator("body")).not_to_contain_text("fail-secret")


def test_stream_manager_v2_start_stop_use_backend_transitional_states(page, live_server):
    profile = applied_profile(live_server)
    state = install_v2_routes(page, profile)
    page.goto(live_server.base_url + "/obs/stream")
    add_destination_v2(page, secret="transition-secret")

    page.locator("#run-preflight").click()
    expect(page.locator("#preflight-pill")).to_contain_text("PASSED")
    page.locator(".v2-destination-head").click()
    start = page.locator('[data-action="start"]')
    expect(start).to_be_enabled()
    start.click()

    # Start ACK is STARTING. The browser must not invent LIVE.
    expect(page.locator(".v2-destination .state-pill").first).to_have_text("STARTING")
    expect(page.locator(".v2-destination")).not_to_contain_text("LIVE")

    # Simulate authoritative backend reconciliation to LIVE.
    state["destinations"][0]["state"] = "LIVE"
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.reload()
    expect(page.locator(".v2-destination .state-pill").first).to_have_text("LIVE", timeout=7000)
    page.locator(".v2-destination-head").click()
    stop = page.locator('[data-action="stop"]')
    expect(stop).to_be_enabled()
    stop.click()
    expect(page.locator(".v2-destination .state-pill").first).to_have_text("STOPPING")
    expect(page.locator("body")).not_to_contain_text("transition-secret")


def test_stream_manager_v2_credential_is_write_only_and_activity_records_actions(page, live_server):
    profile = applied_profile(live_server)
    state = install_v2_routes(page, profile)
    page.goto(live_server.base_url + "/obs/stream")
    add_destination_v2(page, secret="never-render-me")

    assert state["credential_bodies"][0]["credential"] == "never-render-me"
    expect(page.locator("body")).not_to_contain_text("never-render-me")
    expect(page.locator("#activity-log-v2")).to_contain_text("Destination created")

    page.locator("#run-preflight").click()
    expect(page.locator("#activity-log-v2")).to_contain_text("Preflight passed")
