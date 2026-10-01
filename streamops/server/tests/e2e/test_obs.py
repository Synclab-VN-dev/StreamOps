from copy import deepcopy
import json
import re
import shutil
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.only_browser('chromium')

MOBILE_VIEWPORTS = [
    {'width': 360, 'height': 800},
    {'width': 390, 'height': 844},
    {'width': 430, 'height': 932},
]


def open_card(page, selector):
    page.locator(selector).evaluate('el => el.open = true')


def open_new(page, server):
    page.goto(server.base_url + '/obs')
    open_card(page, '#scene-profile-card')
    expect(page.locator('#new-button')).to_be_enabled()
    expect(page.locator('#profile-count')).to_have_text('0 profiles')
    page.locator('#new-button').click()
    expect(page.locator('#profile-summary-state')).to_have_text('Saved')
    expect(page.locator('#new-button')).to_be_enabled()


def add_browser(page, name='Overlay'):
    open_card(page, '#sources-card')
    page.locator('#add-source-button').click()
    page.locator('.source-picker-option[data-source-type="browser_source"] input').check()
    page.locator('#confirm-source-button').click()
    card = page.locator('.source-editor').last
    card.evaluate('el => el.open = true')
    card.get_by_label('Source name', exact=True).fill(name)
    card.get_by_label('Url', exact=True).fill('https://example.invalid/' + name)
    return card


def save(page):
    page.locator('#save-button').click()
    expect(page.locator('#profile-summary-state')).to_have_text('Saved')
    expect(page.locator('#save-button')).to_be_enabled()


@pytest.mark.parametrize('viewport', [
    *MOBILE_VIEWPORTS,
    {'width': 768, 'height': 900},
    {'width': 1440, 'height': 900},
])
def test_source_picker_stays_inside_panel_without_giant_controls(page, live_server, viewport):
    page.set_viewport_size(viewport)
    open_new(page, live_server)
    open_card(page, '#sources-card')
    page.locator('#add-source-button').click()
    expect(page.locator('.source-picker-option')).not_to_have_count(0)
    expect(page.locator('#source-picker')).to_be_visible()
    expect(page.locator('#source-type')).to_have_count(0)

    panel_box = page.locator('#sources-panel').bounding_box()
    assert panel_box is not None
    for selector in ('#add-source-button', '#refresh-inventory', '#confirm-source-button'):
        control_box = page.locator(selector).bounding_box()
        assert control_box is not None
        assert control_box['x'] >= panel_box['x'] - 1
        assert control_box['x'] + control_box['width'] <= panel_box['x'] + panel_box['width'] + 1
        assert control_box['height'] <= 48

    for option in page.locator('.source-picker-option').all():
        option_box = option.bounding_box()
        assert option_box is not None
        assert option_box['height'] <= 88

    assert page.evaluate(
        'document.documentElement.scrollWidth <= document.documentElement.clientWidth'
    )


def test_source_picker_renders_backend_catalog_groups(page, live_server):
    live_server.source_catalog[:] = [
        {'type': 'custom_video', 'label': 'Custom backend video', 'video': True, 'audio': False, 'fields': []},
        {'type': 'custom_audio', 'label': 'Custom backend audio', 'video': False, 'audio': True, 'fields': [
            {'key': 'device_id', 'label': 'Backend device', 'type': 'string', 'inventory': True},
        ]},
    ]
    open_new(page, live_server)
    open_card(page, '#sources-card')
    page.locator('#add-source-button').click()

    expect(page.locator('.source-picker-option')).to_have_count(2)
    expect(page.locator('#source-picker-count')).to_have_text('2 types')
    expect(page.locator('.source-picker-group legend')).to_have_text(['Video', 'Audio'])
    expect(page.locator('#source-picker-options')).to_contain_text('Custom backend video')
    expect(page.locator('#source-picker-options')).to_contain_text('Custom backend audio')
    expect(page.locator('#source-picker-options')).to_contain_text('Inventory: Backend device')


@pytest.mark.parametrize('viewport', [{'width':1440,'height':900}, {'width':390,'height':844}])
def test_real_store_crud_save_as_and_typed_editor(page, live_server, viewport):
    page.set_viewport_size(viewport)
    open_new(page, live_server)
    page.locator('#profile-name').fill('Original')
    card = add_browser(page)
    card.get_by_label('crop left', exact=True).fill('17')
    card.get_by_label('Layer', exact=True).fill('4')
    card.get_by_label('Configure audio', exact=True).check()
    card.get_by_label('Track 1', exact=True).uncheck()
    card.get_by_label('Track 2', exact=True).check()
    save(page)
    original_id = page.locator('#profile-list').input_value()
    original = live_server.obs.get_profile(original_id)
    assert original['sources'][0]['transform']['crop_left'] == 17
    assert original['sources'][0]['audio']['tracks']['2'] is True
    assert live_server.transport.inputs == []
    page.reload()
    open_card(page, '#scene-profile-card')
    open_card(page, '#sources-card')
    page.locator('.source-editor').first.evaluate('el => el.open = true')
    expect(page.get_by_label('crop left', exact=True)).to_have_value('17')
    page.locator('#duplicate-button').click()
    expect(page.locator('#profile-count')).to_have_text('2 profiles')
    page.locator('#profile-name').fill('Independent copy')
    save(page)
    assert live_server.obs.get_profile(original_id) == original
    page.locator('.source-editor').first.evaluate('el => el.open = true')
    page.get_by_role('button', name='Remove source').click()
    add_browser(page, 'New B').get_by_label('Layer', exact=True).fill('9')
    add_browser(page, 'New A').get_by_label('Layer', exact=True).fill('1')
    page.once('dialog', lambda dialog: dialog.accept('Draft copy'))
    page.locator('#save-as-button').click()
    expect(page.locator('#profile-count')).to_have_text('3 profiles')
    copied = live_server.obs.get_profile(page.locator('#profile-list').input_value())
    assert [(s['name'],s['layer']) for s in copied['sources']] == [('New B',9),('New A',1)]
    assert copied['id'] != original_id
    assert not {s['id'] for s in copied['sources']} & {s['id'] for s in original['sources']}
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#delete-button').click()
    expect(page.locator('#profile-count')).to_have_text('2 profiles')
    page.locator('#template-button').click()
    expect(page.locator('#profile-count')).to_have_text('3 profiles')
    expect(page.locator('.source-editor')).not_to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_apply_drift_warn_fail_offline_and_review(page, live_server):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required for real media gates')
    open_new(page, live_server)
    add_browser(page)
    save(page)
    profile = live_server.obs.get_profile(page.locator('#profile-list').input_value())
    page.locator('#apply-button').click()
    expect(page.locator('#obs-result')).to_have_text('--')
    expect(page.locator('#profile-summary-state')).to_have_text('Applied')
    open_card(page, '#canvas-preview-card')
    page.locator('#preview-tab').click()
    expect(page.locator('#scene-preview')).to_be_visible()
    page.locator('#verify-button').click()
    expect(page.locator('#obs-result')).to_have_text('PASS')
    transport = live_server.transport
    transport.input_settings[profile['sources'][0]['obs_name']]['url'] = 'drift'
    page.locator('#verify-button').click()
    expect(page.locator('#obs-result')).to_have_text('FAIL')
    expect(page.locator('#profile-summary-state')).to_have_text('Drifted')
    page.locator('#apply-button').click()
    expect(page.locator('#obs-result')).to_have_text('--')
    page.locator('#verify-button').click()
    expect(page.locator('#obs-result')).to_have_text('PASS')
    transport.create_input(profile['obs_scene_name'], 'Operator', 'browser_source', {})
    page.locator('#verify-button').click()
    expect(page.locator('#obs-result')).to_have_text('WARN')
    open_card(page, '#review-card')
    page.locator('#review-seconds').fill('1')
    page.locator('#review-button').click()
    expect(page.locator('#review-state')).to_have_text('completed', timeout=20000)
    expect(page.locator('#review-checks')).to_contain_text('review.fps')
    expect(page.locator('#activity-log')).to_contain_text('Review queued')
    assert transport.recording is False
    assert transport.current_scene == 'Scene'
    transport.offline = True
    page.locator('#verify-button').click()
    expect(page.locator('#scene-error-message')).to_contain_text('unavailable')
    expect(page.locator('#profile-summary-state')).to_have_text('Failed')
    page.locator('#profile-name').fill('Saved offline')
    save(page)


def test_apply_does_not_run_runtime_verify_before_activate(page, live_server):
    operations = []
    page.on('websocket', lambda websocket: websocket.on('framesent', lambda payload: operations.append(json.loads(payload).get('operation'))))
    open_new(page, live_server)
    add_browser(page)
    save(page)
    operations.clear()

    page.locator('#apply-button').click()

    expect(page.locator('#profile-summary-state')).to_have_text('Applied')
    expect(page.locator('#obs-result')).to_have_text('--')
    expect(page.locator('#activity-log')).to_contain_text('apply: changed')
    expect(page.locator('#apply-button')).to_be_enabled()
    assert 'scene_profiles.apply' in operations
    assert 'scene_profiles.verify' not in operations
    assert 'apply: FAIL' not in page.locator('#activity-log').inner_text()

    operations.clear()
    page.locator('#activate-button').click()

    expect(page.locator('#obs-result')).to_have_text('PASS')
    expect(page.locator('#activate-button')).to_be_enabled()
    assert operations == ['scene_profiles.activate', 'scene_profiles.verify']



def test_scene_runtime_actions_follow_obs_readiness(page, live_server):
    live_server.obs_process.set_stopped()
    open_new(page, live_server)
    add_browser(page)
    save(page)
    profile_id = page.locator('#profile-list').input_value()

    expect(page.locator('#apply-button')).to_be_disabled(timeout=7000)
    expect(page.locator('#verify-button')).to_be_disabled()
    page.locator('#profile-name').fill('Saved while OBS stopped')
    save(page)

    blocked = page.request.post(live_server.base_url + f'/api/v1/scene-profiles/{profile_id}/apply')
    assert blocked.status == 409
    assert blocked.json()['error']['code'] == 'scene_operation_failed'
    assert 'STOPPED' in blocked.json()['error']['message']

    live_server.obs_process.set_ready(5300)
    expect(page.locator('#apply-button')).to_be_enabled(timeout=7000)
    page.locator('#apply-button').click()
    expect(page.locator('#profile-summary-state')).to_have_text('Applied')
    expect(page.locator('#obs-result')).to_have_text('--')


def test_invalid_required_settings_and_corrupt_file(page, live_server):
    root = live_server.obs.profile_store.root
    root.mkdir(exist_ok=True)
    (root/'corrupt.json').write_text('{broken', encoding='utf-8')
    open_new(page, live_server)
    expect(page.locator('#store-errors')).to_contain_text('corrupt.json')
    open_card(page, '#sources-card')
    page.locator('#add-source-button').click()
    page.locator('.source-picker-option[data-source-type="display_capture"] input').check()
    page.locator('#confirm-source-button').click()
    page.locator('#save-button').click()
    expect(page.locator('#scene-error-message')).to_contain_text('monitor_id')
    page.locator('.source-editor').last.evaluate('el => el.open = true')
    page.get_by_label('Monitor id', exact=True).select_option(r'\\.\DISPLAY1')
    save(page)
    profile_id = page.locator('#profile-list').input_value()
    profile = live_server.obs.get_profile(profile_id)
    payload = deepcopy(profile)
    payload['sources'][0]['settings']['arbitrary'] = 'blocked'
    response = page.request.put(live_server.base_url+'/api/v1/scene-profiles/'+profile_id, data=payload)
    assert response.status == 422
    assert live_server.obs.get_profile(profile_id) == profile


def test_obs_cards_default_collapsed_with_domain_summaries(page, live_server):
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(live_server.base_url + '/obs')

    for selector in (
        '#obs-status-panel',
        '#scene-profile-card',
        '#sources-card',
        '#canvas-preview-card',
        '#verification-card',
        '#review-card',
        '#activity-card',
    ):
        expect(page.locator(selector)).not_to_have_attribute('open', '')

    expect(page.locator('#runtime-summary-uptime')).not_to_have_text('')
    expect(page.locator('#profile-summary-canvas')).not_to_have_text('')
    expect(page.locator('#source-summary-catalog')).to_contain_text('types')


def test_healthy_websocket_stops_status_polling(page, live_server):
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.goto(live_server.base_url + '/obs')
    expect(page.locator('#obs-state')).to_have_text('READY')
    page.wait_for_timeout(5500)

    assert not any(url.endswith('/api/v1/health') for url in requests)
    assert not any(url.endswith('/api/v1/obs/process/status') for url in requests)


@pytest.mark.parametrize('viewport', MOBILE_VIEWPORTS)
def test_dashboard_uses_one_socket_and_no_business_rest(page, live_server, viewport):
    page.set_viewport_size(viewport)
    sockets = []
    requests = []
    page.on('websocket', lambda websocket: sockets.append(websocket))
    page.on('request', lambda request: requests.append(request.url))
    open_new(page, live_server)
    add_browser(page)
    save(page)
    page.locator('#verify-button').click()
    expect(page.locator('#obs-result')).not_to_have_text('--')

    assert len(sockets) == 1
    business_http = [
        url for url in requests
        if '/api/v1/' in url
        and '/preview' not in url
        and '/artifacts/' not in url
    ]
    assert business_http == []


@pytest.mark.parametrize('viewport', MOBILE_VIEWPORTS)
def test_initial_profile_selection_matches_current_obs_scene(page, live_server, viewport):
    page.set_viewport_size(viewport)
    first = live_server.obs.create_profile({'name': 'Alpha profile', 'obs_scene_name': 'Alpha Scene'})
    second = live_server.obs.create_profile({'name': 'Live profile', 'obs_scene_name': 'Live Scene'})
    live_server.transport.current_scene = second['obs_scene_name']

    page.goto(live_server.base_url + '/obs')
    open_card(page, '#scene-profile-card')

    expect(page.locator('#profile-list')).to_have_value(second['id'])
    expect(page.locator('#profile-name')).to_have_value('Live profile')
    expect(page.locator('#profile-runtime-state')).to_have_text('ACTIVE')
    assert page.locator('#profile-list').input_value() != first['id']


@pytest.mark.parametrize('viewport', MOBILE_VIEWPORTS)
def test_reconnect_preserves_dirty_draft_and_page_lifecycle(page, live_server, viewport):
    page.set_viewport_size(viewport)
    sockets = []
    requests = []
    page.on('websocket', lambda websocket: sockets.append(websocket))
    page.on('request', lambda request: requests.append(request.url))
    open_new(page, live_server)
    page.locator('#profile-name').fill('Unsaved operator draft')
    expect(page.locator('#profile-summary-state')).to_have_text('Modified')
    assert len(sockets) == 1

    page.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, value: 'hidden'}); document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(500)
    assert len(sockets) == 1
    assert page.evaluate('window.StreamOpsObs.connected') is True
    page.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, value: 'visible'}); document.dispatchEvent(new Event('visibilitychange'))")

    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    page.wait_for_timeout(1500)
    assert len(sockets) == 1
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow'))")
    expect(page.locator('#activity-log')).to_contain_text('Profile manager synchronized', timeout=7000)
    expect(page.locator('#profile-name')).to_have_value('Unsaved operator draft')
    expect(page.locator('#profile-summary-state')).to_have_text('Modified')
    assert len(sockets) == 2

    assert not any('/api/v1/' in url and '/preview' not in url and '/artifacts/' not in url for url in requests)


def test_websocket_reconnects_without_http_fallback(page, live_server):
    page.add_init_script("""
      (() => {
        const NativeWebSocket = window.WebSocket;
        let attempts = 0;
        window.WebSocket = function(url, protocols) {
          attempts += 1;
          if (attempts <= 2) {
            const failed = new EventTarget();
            failed.readyState = 3;
            failed.close = () => {};
            setTimeout(() => {
              failed.dispatchEvent(new Event('error'));
              failed.dispatchEvent(new CloseEvent('close'));
            }, 0);
            return failed;
          }
          return protocols === undefined ? new NativeWebSocket(url) : new NativeWebSocket(url, protocols);
        };
        for (const key of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED']) window.WebSocket[key] = NativeWebSocket[key];
      })();
    """)
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.goto(live_server.base_url + '/obs')

    expect(page.locator('#activity-log')).to_contain_text('OBS dashboard connection established', timeout=10000)
    assert not any(url.endswith('/api/v1/obs/process/status') for url in requests)
    assert not any(url.endswith('/api/v1/health') for url in requests)
    page.wait_for_timeout(5500)
    assert not any(url.endswith('/api/v1/obs/process/status') for url in requests)


@pytest.mark.parametrize('viewport', MOBILE_VIEWPORTS)
def test_profile_runtime_state_tracks_external_scene_without_reload(page, live_server, viewport):
    page.set_viewport_size(viewport)
    open_new(page, live_server)
    profile = live_server.obs.get_profile(page.locator('#profile-list').input_value())
    expect(page.locator('#profile-runtime-state')).to_have_text('INACTIVE')

    live_server.transport.current_scene = profile['obs_scene_name']
    expect(page.locator('#profile-runtime-state')).to_have_text('ACTIVE', timeout=3000)
    expect(page.locator('#profile-summary-state')).to_have_text('Saved')

    live_server.transport.current_scene = 'Operator external scene'
    expect(page.locator('#profile-runtime-state')).to_have_text('INACTIVE', timeout=3000)
    expect(page.locator('#profile-summary-state')).to_have_text('Saved')
    expect(page.locator('#canvas-summary-fps')).not_to_have_text('')
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')


def test_profile_selector_is_compact_and_obs_theme_matches_reference(page, live_server):
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(live_server.base_url + '/obs')
    open_card(page, '#scene-profile-card')

    profile_list = page.locator('#profile-list')
    expect(profile_list).not_to_have_attribute('size', '6')
    profile_box = profile_list.bounding_box()
    assert profile_box is not None
    assert profile_box['height'] <= 48
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == 'rgb(245, 246, 248)'
    assert page.locator('#scene-profile-card').evaluate("el => getComputedStyle(el).backgroundColor") == 'rgb(255, 255, 255)'
    assert float(page.locator('#scene-profile-card').evaluate("el => getComputedStyle(el).borderRadius.replace('px', '')")) >= 20
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')


def test_verification_keeps_expected_actual_and_review_is_separate(page, live_server):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required for real media gates')
    page.set_viewport_size({'width': 390, 'height': 844})
    open_new(page, live_server)
    add_browser(page)
    save(page)

    page.locator('#apply-button').click()
    page.locator('#verify-button').click()
    open_card(page, '#verification-card')
    expect(page.locator('#verify-checks')).not_to_have_count(0)
    first_check = page.locator('#verify-checks .verification-check').first
    first_check.evaluate('el => el.open = true')
    expect(first_check).to_contain_text('Expected')
    expect(first_check).to_contain_text('Actual')
    expect(page.locator('#verification-ready')).to_have_text('Yes')
    expect(page.locator('#verification-generated')).not_to_have_text('--')
    expect(page.locator('#verification-obs-version')).not_to_have_text('--')

    verification_text = page.locator('#verify-checks').inner_text()
    open_card(page, '#review-card')
    page.locator('#review-seconds').fill('1')
    page.locator('#review-run-button').click()
    expect(page.locator('#review-state')).to_have_text('completed', timeout=20000)
    review_details = page.locator('#review-result-checks')
    expect(review_details).not_to_have_attribute('open', '')
    expect(page.locator('#review-check-summary')).to_have_text(re.compile(r'\d+P · \d+W · \d+F'))
    review_details.evaluate('el => el.open = true')
    expect(page.locator('#review-checks')).to_contain_text('review.fps')
    first_review_check = page.locator('#review-checks .verification-check').first
    first_review_check.evaluate('el => el.open = true')
    expect(first_review_check).to_contain_text('Expected')
    expect(first_review_check).to_contain_text('Actual')

    artifact_rows = page.locator('#review-artifacts .artifact-row')
    expect(artifact_rows).not_to_have_count(0)
    assert int(page.locator('#review-artifact-count').inner_text()) == artifact_rows.count()
    artifact_text = page.locator('#review-artifacts').inner_text()
    assert '\\' not in artifact_text
    assert '/tmp/' not in artifact_text
    assert all('/api/v1/scene-reviews/' in href for href in page.locator('#review-artifacts a').evaluate_all('links => links.map(link => link.href)'))

    preview_open = page.locator('.artifact-row', has_text='preview.png').get_by_role('link', name='Open')
    with page.expect_popup() as popup_info:
        preview_open.click()
    popup = popup_info.value
    popup.wait_for_load_state()
    assert '/artifacts/preview' in popup.url
    popup.close()

    with page.expect_download() as download_info:
        page.locator('.artifact-row', has_text='verify.json').get_by_role('link', name='Download').click()
    assert download_info.value.suggested_filename == 'verify.json'
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
    assert page.locator('#verify-checks').inner_text() == verification_text


def test_new_source_subcard_is_collapsed_and_updates_summary(page, live_server):
    open_new(page, live_server)
    open_card(page, '#sources-card')
    page.locator('#add-source-button').click()
    page.locator('.source-picker-option[data-source-type="browser_source"] input').check()
    page.locator('#confirm-source-button').click()

    source = page.locator('.source-editor').last
    expect(source).not_to_have_attribute('open', '')
    expect(page.locator('#source-summary-configured')).to_have_text('1')
    expect(page.locator('#source-summary-enabled')).to_have_text('1')

    source.evaluate('el => el.open = true')
    source.get_by_label('Source enabled', exact=True).uncheck()
    expect(page.locator('#source-summary-enabled')).to_have_text('0')
