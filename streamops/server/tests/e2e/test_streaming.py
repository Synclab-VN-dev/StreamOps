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
    return server.obs.get_profile(profile["id"])


def add_destination(page, name: str, *, secret: str = "browser-stream-secret") -> str:
    destination_id = name.lower().replace(" ", "-")
    expect(page.locator('.stream-v2[data-ready="true"]')).to_be_attached()
    page.locator("#add-destination").click()
    editor = page.locator("#destination-editor")
    expect(editor).to_be_visible()
    page.locator("#destination-name").fill(name)
    page.locator("#destination-url").fill(f"rtmp://127.0.0.1:1935/{destination_id}")
    page.locator("#destination-credential").fill(secret)
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and response.url.endswith("/api/v1/multistream/destinations")
    ):
        page.locator("#editor-save").click()
    expect(editor).not_to_be_visible()
    expect(page.locator(f'.v2-destination[data-id="{destination_id}"]')).to_be_visible()
    expect(page.locator("#destination-credential")).to_have_value("")
    expect(page.locator("body")).not_to_contain_text(secret)
    return destination_id


def run_preflight(page) -> None:
    page.locator("#run-preflight").click()
    expect(page.locator("#preflight-pill")).to_contain_text("PASSED")


def set_runtime(server, destination_id: str, state: str) -> None:
    item = server.multistream.repository.get(destination_id)
    server.multistream_adapter.set_state(item["plugin_target_id"], state)
    assert server.multistream.status(destination_id)["state"] == state


def destination_card(page, destination_id: str):
    return page.locator(f'.v2-destination[data-id="{destination_id}"]')


def expect_state(page, destination_id: str, state: str) -> None:
    expect(destination_card(page, destination_id).locator(".state-pill").first).to_have_text(
        state, timeout=7000
    )


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
    expect(page.locator("#open-streaming")).to_be_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


@pytest.mark.parametrize("width,height", [(1440, 1000), (768, 1024), (390, 844)])
def test_stream_manager_v2_visual_hierarchy_is_responsive(page, live_server, width, height):
    profile = applied_profile(live_server)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(live_server.base_url + "/obs/stream")

    expect(page.locator(".v2-header h1")).to_have_text("Stream Manager")
    expect(page.locator("#obs-state")).to_have_text("● READY", timeout=7000)
    expect(page.locator("#obs-profile")).to_have_text(profile["name"])
    expect(page.locator("#obs-scene")).to_have_text(profile["obs_scene_name"])
    expect(page.locator("#obs-canvas")).to_have_text(
        f'{profile["canvas"]["width"]}×{profile["canvas"]["height"]}'
    )
    expect(page.locator("#preflight-pill")).to_have_text("NOT RUN")
    expect(page.locator("#preflight-error")).to_be_hidden()
    expect(page.locator("#destination-empty")).to_be_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )

    page.locator("#add-destination").click()
    modal = page.locator("#destination-editor")
    expect(modal).to_be_in_viewport()
    box = modal.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
    expect(page.locator("#credential-label")).to_have_text("Stream key")
    expect(page.locator("#editor-delete")).to_be_hidden()
    page.locator("#editor-cancel").click()


def test_stream_manager_v2_preflight_fail_blocks_start(page, live_server):
    applied_profile(live_server)

    def fail_preflight(route):
        payload = route.request.post_data_json
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": "FAIL",
                    "profile_id": payload["profile_id"],
                    "checks": [
                        {"id": "obs_ready", "status": "PASS", "message": "OBS ready"},
                        {"id": "video_capture", "status": "FAIL", "message": "Video capture inactive"},
                    ],
                }
            ),
        )

    page.route("**/api/v1/live/preflight/shared", fail_preflight)
    page.goto(live_server.base_url + "/obs/stream")
    destination_id = add_destination(page, "Fail Target", secret="fail-secret")
    page.locator("#run-preflight").click()
    expect(page.locator("#preflight-pill")).to_contain_text("FAILED")
    destination_card(page, destination_id).locator(".v2-destination-head").click()
    expect(destination_card(page, destination_id).locator('[data-action="start"]')).to_be_disabled()
    expect(page.locator("body")).not_to_contain_text("fail-secret")


def test_stream_manager_v2_rest_and_ws_transitions_are_authoritative(page, live_server):
    applied_profile(live_server)
    page.goto(live_server.base_url + "/obs/stream")
    destination_id = add_destination(page, "Transition Target", secret="transition-secret")
    run_preflight(page)
    card = destination_card(page, destination_id)
    card.locator(".v2-destination-head").click()
    card.locator('[data-action="start"]').click()

    # REST ACK remains transitional until an authoritative backend event arrives.
    expect_state(page, destination_id, "STARTING")
    expect(card).not_to_contain_text("Backend confirmed live")
    set_runtime(live_server, destination_id, "LIVE")
    expect_state(page, destination_id, "LIVE")
    expect(card).to_contain_text("6.0 Mbps", timeout=7000)

    card.locator('[data-action="stop"]').click()
    expect_state(page, destination_id, "STOPPING")
    set_runtime(live_server, destination_id, "IDLE")
    expect_state(page, destination_id, "IDLE")
    expect(page.locator("body")).not_to_contain_text("transition-secret")


def test_stream_manager_v2_mixed_states_reload_and_ws_reconnect(page, live_server):
    applied_profile(live_server)
    page.goto(live_server.base_url + "/obs/stream")
    destination_a = add_destination(page, "Destination A", secret="secret-a")
    destination_b = add_destination(page, "Destination B", secret="secret-b")

    set_runtime(live_server, destination_a, "LIVE")
    set_runtime(live_server, destination_b, "FAILED")
    expect_state(page, destination_a, "LIVE")
    expect_state(page, destination_b, "FAILED")

    set_runtime(live_server, destination_b, "RECONNECTING")
    expect_state(page, destination_a, "LIVE")
    expect_state(page, destination_b, "RECONNECTING")

    page.reload()
    expect_state(page, destination_a, "LIVE")
    expect_state(page, destination_b, "RECONNECTING")

    page.context.set_offline(True)
    set_runtime(live_server, destination_b, "LIVE")
    page.context.set_offline(False)
    expect_state(page, destination_a, "LIVE")
    expect_state(page, destination_b, "LIVE")
    expect(page.locator("#activity-log-v2")).not_to_contain_text("destination.state_changed")


def test_stream_manager_v2_credential_edit_and_delete_are_write_only(page, live_server):
    applied_profile(live_server)
    page.goto(live_server.base_url + "/obs/stream")
    destination_id = add_destination(page, "CRUD Target", secret="never-render-me")
    card = destination_card(page, destination_id)
    expect(card).to_contain_text("Stream key")
    expect(card).to_contain_text("Configured")
    card.locator(".v2-destination-head").click()
    card.locator('[data-action="edit"]').click()

    expect(page.locator("#credential-label")).to_have_text("Replace stream key")
    expect(page.locator("#destination-credential")).to_have_value("")
    expect(page.locator("#credential-help")).to_contain_text("never loaded")
    expect(page.locator("#editor-delete")).to_be_visible()
    page.locator("#destination-name").fill("CRUD Target Updated")
    page.locator("#editor-save").click()
    expect(card).to_contain_text("CRUD Target Updated")
    expect(page.locator("body")).not_to_contain_text("never-render-me")

    card.locator('[data-action="edit"]').click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#editor-delete").click()
    expect(destination_card(page, destination_id)).to_have_count(0)
    expect(page.locator("#activity-log-v2")).to_contain_text("Destination deleted")
