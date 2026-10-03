from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from streamops.server.errors import StreamingError

pytestmark = pytest.mark.only_browser('chromium')


def open_card(page, selector: str) -> None:
    page.locator(selector).evaluate('el => el.open = true')


def applied_profile(server, name: str = 'Streaming Profile'):
    profile = server.obs.create_profile({'name': name})
    server.obs.apply_profile(profile['id'])
    server.obs.activate_profile(profile['id'])
    verified = server.obs.verify_profile(profile['id'], runtime=True)
    assert verified.status == 'PASS'
    return profile


def create_destination_ui(page, *, name: str = 'LAN Test', secret: str = 'browser-stream-secret') -> None:
    open_card(page, '#stream-destination-card')
    page.locator('#new-destination-button').click()
    page.locator('#destination-name').fill(name)
    page.get_by_label('Server URL', exact=True).fill('rtmp://127.0.0.1:1935/live')
    page.locator('#save-destination-button').click()
    expect(page.locator('#destination-summary-name')).to_have_text(name)
    page.locator('#credential-input').fill(secret)
    page.locator('#save-credential-button').click()
    expect(page.locator('#credential-status')).to_have_text('Configured')
    expect(page.locator('#credential-input')).to_have_value('')


def test_stream_page_uses_only_live_socket_and_no_live_status_polling(page, live_server):
    page.set_viewport_size({'width': 390, 'height': 844})
    sockets = []
    requests = []
    page.on('websocket', lambda websocket: sockets.append(websocket))
    page.on('request', lambda request: requests.append(request.url))

    page.goto(live_server.base_url + '/obs/stream')
    expect(page.locator('#stream-page-state')).to_have_text('IDLE', timeout=7000)
    page.wait_for_timeout(1200)

    assert len(sockets) == 1
    assert '/api/v1/live/ws' in sockets[0].url
    assert not any('/api/v1/obs/ws' in socket.url for socket in sockets)
    assert not any(url.endswith('/api/v1/live/status') for url in requests)
    assert page.locator('#obs-status-panel').count() == 0
    assert page.locator('#sources-card').count() == 0
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')


def test_dirty_scene_profile_survives_stream_navigation_and_blocks_start(page, live_server):
    live_server.obs.create_profile({'name': 'AAA Other Profile'})
    profile = applied_profile(live_server)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(live_server.base_url + '/obs')
    open_card(page, '#scene-profile-card')
    expect(page.locator('#profile-list')).to_have_value(profile['id'])
    page.locator('#profile-name').fill('Unsaved operator draft')
    expect(page.locator('#profile-summary-state')).to_have_text('Modified')
    expect(page.locator('#streaming-state-pill')).to_have_text('IDLE', timeout=7000)

    open_card(page, '#streaming-card')
    page.locator('#open-streaming').click()
    expect(page).to_have_url(live_server.base_url + '/obs/stream')
    expect(page.locator('#stream-profile-list')).to_have_value(profile['id'])
    open_card(page, '#stream-setup-card')
    expect(page.locator('#dirty-profile-warning')).to_be_visible()
    expect(page.locator('#setup-draft-state')).to_have_text('Unsaved changes')

    create_destination_ui(page, secret='dirty-guard-secret')
    open_card(page, '#stream-preflight-card')
    page.locator('#run-preflight-button').click()
    expect(page.locator('#preflight-state')).to_have_text('PASS')
    open_card(page, '#stream-live-card')
    expect(page.locator('#start-stream-button')).to_be_disabled()
    assert 'dirty-guard-secret' not in page.locator('body').inner_text()

    page.locator('.stream-back-link').click()
    expect(page).to_have_url(live_server.base_url + '/obs')
    open_card(page, '#scene-profile-card')
    expect(page.locator('#profile-name')).to_have_value('Unsaved operator draft')
    expect(page.locator('#profile-summary-state')).to_have_text('Modified')


def test_streaming_full_custom_rtmp_lifecycle_and_secret_redaction(page, live_server):
    profile = applied_profile(live_server)
    sockets = []
    requests = []
    operations = []
    def on_socket(websocket):
        sockets.append(websocket)
        websocket.on(
            'framesent',
            lambda payload: operations.append(json.loads(payload).get('operation')),
        )
    page.on('websocket', on_socket)
    page.on('request', lambda request: requests.append(request.url))

    page.goto(live_server.base_url + '/obs/stream')
    expect(page.locator('#stream-page-state')).to_have_text('IDLE', timeout=7000)
    expect(page.locator('#stream-profile-list')).to_have_value(profile['id'])

    create_destination_ui(page, secret='first-browser-secret')
    assert 'first-browser-secret' not in page.locator('body').inner_text()

    # Replace and remove are separate secret operations; plaintext is never rendered back.
    page.locator('#credential-input').fill('replacement-browser-secret')
    page.locator('#save-credential-button').click()
    expect(page.locator('#credential-input')).to_have_value('')
    page.locator('#delete-credential-button').click()
    expect(page.locator('#credential-status')).to_have_text('Not configured')
    page.locator('#credential-input').fill('final-browser-secret')
    page.locator('#save-credential-button').click()
    expect(page.locator('#credential-status')).to_have_text('Configured')
    expect(page.locator('#credential-input')).to_have_value('')

    # Public destination settings remain editable while IDLE.
    page.locator('#destination-name').fill('LAN Test Renamed')
    page.locator('#destination-enabled').uncheck()
    page.locator('#save-destination-button').click()
    expect(page.locator('#destination-state-pill')).to_have_text('DISABLED')
    page.locator('#destination-enabled').check()
    page.locator('#save-destination-button').click()
    expect(page.locator('#destination-summary-name')).to_have_text('LAN Test Renamed')

    open_card(page, '#stream-preflight-card')
    page.locator('#run-preflight-button').click()
    expect(page.locator('#preflight-state')).to_have_text('PASS')
    expect(page.locator('#preflight-checks')).to_contain_text('obs_ready')
    expect(page.locator('#preflight-checks')).to_contain_text('profile_verify')

    open_card(page, '#stream-live-card')
    expect(page.locator('#start-stream-button')).to_be_enabled()
    operations.clear()
    page.evaluate("() => { const button = document.querySelector('#start-stream-button'); button.click(); button.click(); }")
    expect(page.locator('#live-state-pill')).to_have_text('LIVE', timeout=7000)
    assert operations.count('live.start') == 1
    expect(page.locator('#live-output-active')).to_have_text('Yes')
    expect(page.locator('#destination-name')).to_be_disabled()
    assert live_server.transport.streaming is True
    assert 'final-browser-secret' not in page.locator('body').inner_text()

    # The /obs overview is a separate page but must reconcile the same managed
    # server session, then navigate back without inventing a second Start.
    page.locator('.stream-back-link').click()
    expect(page).to_have_url(live_server.base_url + '/obs')
    expect(page.locator('#streaming-state-pill')).to_have_text('LIVE', timeout=7000)
    expect(page.locator('#streaming-summary-destination')).to_have_text('LAN Test Renamed')
    open_card(page, '#streaming-card')
    expect(page.locator('#streaming-overview-preflight')).to_have_text('PASS')
    page.locator('#open-streaming').click()
    expect(page).to_have_url(live_server.base_url + '/obs/stream')
    expect(page.locator('#live-state-pill')).to_have_text('LIVE', timeout=7000)

    # Force transport reconnect; fresh server snapshot must recover LIVE without a second Start.
    live_socket_count = sum('/api/v1/live/ws' in socket.url for socket in sockets)
    page.evaluate('window.StreamOpsLive.socket.close()')
    page.wait_for_function('() => window.StreamOpsLive.connected === false', timeout=5000)
    expect(page.locator('#live-state-pill')).to_have_text('RECONNECTING')
    expect(page.locator('#stop-stream-button')).to_be_disabled()
    page.wait_for_function('() => window.StreamOpsLive.connected === true', timeout=10000)
    expect(page.locator('#live-state-pill')).to_have_text('LIVE', timeout=7000)
    assert sum('/api/v1/live/ws' in socket.url for socket in sockets) == live_socket_count + 1

    # Full reload must also recover the managed server-side session.
    page.reload()
    expect(page.locator('#live-state-pill')).to_have_text('LIVE', timeout=7000)
    expect(page.locator('#live-summary-destination')).to_have_text('LAN Test Renamed')
    assert 'final-browser-secret' not in page.locator('body').inner_text()
    open_card(page, '#stream-live-card')
    expect(page.locator('#stop-stream-button')).to_be_visible()
    operations.clear()
    page.evaluate("() => { const button = document.querySelector('#stop-stream-button'); button.click(); button.click(); }")
    expect(page.locator('#live-state-pill')).to_have_text('IDLE', timeout=7000)
    assert operations.count('live.stop') == 1
    assert live_server.transport.streaming is False
    assert live_server.transport.stream_service['streamServiceType'] == 'rtmp_common'
    assert live_server.live.session_store.load_session() is None
    assert live_server.live.session_store.has_restore() is False

    # Cleanup remains available after managed session cleanup.
    open_card(page, '#stream-destination-card')
    page.locator('#delete-credential-button').click()
    expect(page.locator('#credential-status')).to_have_text('Not configured')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#delete-destination-button').click()
    expect(page.locator('#destination-summary-name')).to_have_text('--')

    body = page.locator('body').inner_text()
    for secret in ('first-browser-secret', 'replacement-browser-secret', 'final-browser-secret'):
        assert secret not in body
    assert not any(url.endswith('/api/v1/live/status') for url in requests)
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')


@pytest.mark.parametrize('server_state', ['RECOVERY_REQUIRED', 'RESTORE_FAILED'])
def test_stream_page_renders_recovery_state_without_normalizing_to_idle(
    page, live_server, server_state
):
    profile = live_server.obs.create_profile({'name': 'Recovery Profile'})
    destination = live_server.live.create_destination({
        'name': 'Recovery Destination',
        'type': 'custom_rtmp',
        'enabled': True,
        'settings': {'server_url': 'rtmp://127.0.0.1:1935/live'},
    })
    session = {
        'schema_version': 1,
        'session_id': 'browser-recovery-session',
        'state': server_state,
        'profile_id': profile['id'],
        'destination_ids': [destination['id']],
        'started_at': '2026-10-03T00:00:00+00:00',
    }
    live_server.live._session = session
    live_server.live.session_store.save_session(session)
    live_server.live.session_store.save_restore({
        'streamServiceType': 'rtmp_common',
        'streamServiceSettings': {'service': 'Existing'},
    })

    page.goto(live_server.base_url + '/obs/stream')
    expect(page.locator('#stream-page-state')).to_have_text(server_state, timeout=7000)
    open_card(page, '#stream-live-card')
    expect(page.locator('#start-stream-button')).to_be_hidden()
    expect(page.locator('#stop-stream-button')).to_be_visible()
    expect(page.locator('#stop-stream-button')).to_have_text('Retry Stop / Restore')
    open_card(page, '#stream-destination-card')
    expect(page.locator('#destination-name')).to_be_disabled()


def test_stream_page_renders_obs_not_ready(page, live_server):
    live_server.obs_process.set_stopped()
    page.goto(live_server.base_url + '/obs/stream')
    expect(page.locator('#stream-page-state')).to_have_text('OBS_NOT_READY', timeout=7000)
    open_card(page, '#stream-live-card')
    expect(page.locator('#start-stream-button')).to_be_visible()
    expect(page.locator('#start-stream-button')).to_be_disabled()
    expect(page.locator('#stop-stream-button')).to_be_hidden()



def test_preflight_fail_blocks_start_and_typed_start_error_is_rendered(page, live_server):
    profile = applied_profile(live_server, 'Typed Error Profile')
    page.goto(live_server.base_url + '/obs/stream')
    expect(page.locator('#stream-page-state')).to_have_text('IDLE', timeout=7000)
    expect(page.locator('#stream-profile-list')).to_have_value(profile['id'])

    # Missing credential is a server-owned preflight failure and must keep Start blocked.
    open_card(page, '#stream-destination-card')
    page.locator('#new-destination-button').click()
    page.locator('#destination-name').fill('Typed Error Destination')
    page.get_by_label('Server URL', exact=True).fill('rtmp://127.0.0.1:1935/live')
    page.locator('#save-destination-button').click()
    open_card(page, '#stream-preflight-card')
    page.locator('#run-preflight-button').click()
    expect(page.locator('#preflight-state')).to_have_text('FAIL')
    expect(page.locator('#preflight-checks')).to_contain_text('credential')
    open_card(page, '#stream-live-card')
    expect(page.locator('#start-stream-button')).to_be_disabled()

    # Once preflight passes, a typed backend Start failure is surfaced without
    # inventing a local IDLE transition or leaking the credential.
    open_card(page, '#stream-destination-card')
    page.locator('#credential-input').fill('typed-error-secret')
    page.locator('#save-credential-button').click()
    open_card(page, '#stream-preflight-card')
    page.locator('#run-preflight-button').click()
    expect(page.locator('#preflight-state')).to_have_text('PASS')

    original_start = live_server.live.start

    def fail_start(_profile_id: str, _destination_id: str):
        raise StreamingError('stream_start_failed', 'Synthetic typed start failure.', 409)

    live_server.live.start = fail_start
    try:
        open_card(page, '#stream-live-card')
        expect(page.locator('#start-stream-button')).to_be_enabled()
        page.locator('#start-stream-button').click()
        expect(page.locator('#live-error')).to_contain_text(
            'stream_start_failed: Synthetic typed start failure.'
        )
        expect(page.locator('#live-state-pill')).to_have_text('IDLE')
        assert 'typed-error-secret' not in page.locator('body').inner_text()
    finally:
        live_server.live.start = original_start
