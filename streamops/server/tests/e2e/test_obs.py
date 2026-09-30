from copy import deepcopy
import shutil
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.only_browser('chromium')


def open_card(page, selector):
    page.locator(selector).evaluate('el => el.open = true')


def open_new(page, server):
    page.goto(server.base_url + '/obs')
    open_card(page, '#scene-profile-card')
    expect(page.locator('#new-button')).to_be_enabled()
    expect(page.locator('#profile-count')).to_have_text('0 profiles')
    page.locator('#new-button').click()
    expect(page.locator('#editor-state')).to_have_text('Saved')


def add_browser(page, name='Overlay'):
    open_card(page, '#sources-card')
    page.locator('#source-type').select_option('browser_source')
    page.locator('#add-source-button').click()
    card = page.locator('.source-editor').last
    card.get_by_label('Source name', exact=True).fill(name)
    card.get_by_label('Url', exact=True).fill('https://example.invalid/' + name)
    return card


def save(page):
    page.locator('#save-button').click()
    expect(page.locator('#editor-state')).to_have_text('Saved')
    expect(page.locator('#save-button')).to_be_enabled()


@pytest.mark.parametrize('viewport', [
    {'width': 390, 'height': 844},
    {'width': 768, 'height': 900},
    {'width': 1440, 'height': 900},
])
def test_source_actions_stay_inside_panel(page, live_server, viewport):
    page.set_viewport_size(viewport)
    page.goto(live_server.base_url + '/obs')
    open_card(page, '#sources-card')
    expect(page.locator('#source-type option')).not_to_have_count(0)

    panel_box = page.locator('#sources-panel').bounding_box()
    assert panel_box is not None
    for selector in ('#source-type', '#add-source-button', '#refresh-inventory'):
        control_box = page.locator(selector).bounding_box()
        assert control_box is not None
        assert control_box['x'] >= panel_box['x'] - 1
        assert control_box['x'] + control_box['width'] <= panel_box['x'] + panel_box['width'] + 1

    assert page.evaluate(
        'document.documentElement.scrollWidth <= document.documentElement.clientWidth'
    )


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
    expect(page.locator('#editor-state')).to_have_text('Applied')
    expect(page.locator('#scene-preview')).to_be_visible()
    page.locator('#verify-button').click()
    expect(page.locator('#obs-result')).to_have_text('PASS')
    transport = live_server.transport
    transport.input_settings[profile['sources'][0]['obs_name']]['url'] = 'drift'
    page.locator('#verify-button').click()
    expect(page.locator('#obs-result')).to_have_text('FAIL')
    expect(page.locator('#editor-state')).to_have_text('Drifted')
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
    expect(page.locator('#editor-state')).to_have_text('Failed')
    page.locator('#profile-name').fill('Saved offline')
    save(page)


def test_apply_does_not_run_runtime_verify_before_activate(page, live_server):
    open_new(page, live_server)
    add_browser(page)
    save(page)
    profile_id = page.locator('#profile-list').input_value()
    requests = []
    page.on('request', lambda request: requests.append(request.url))

    page.locator('#apply-button').click()

    expect(page.locator('#editor-state')).to_have_text('Applied')
    expect(page.locator('#obs-result')).to_have_text('--')
    expect(page.locator('#activity-log')).to_contain_text('apply: changed')
    expect(page.locator('#apply-button')).to_be_enabled()
    verify_path = f'/api/v1/scene-profiles/{profile_id}/verify'
    assert not any(url.endswith(verify_path) for url in requests)
    assert 'apply: FAIL' not in page.locator('#activity-log').inner_text()

    requests.clear()
    page.locator('#activate-button').click()

    expect(page.locator('#obs-result')).to_have_text('PASS')
    expect(page.locator('#activate-button')).to_be_enabled()
    assert any(url.endswith(f'/api/v1/scene-profiles/{profile_id}/activate') for url in requests)
    assert any(url.endswith(verify_path) for url in requests)



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
    expect(page.locator('#editor-state')).to_have_text('Applied')
    expect(page.locator('#obs-result')).to_have_text('--')


def test_invalid_required_settings_and_corrupt_file(page, live_server):
    root = live_server.obs.profile_store.root
    root.mkdir(exist_ok=True)
    (root/'corrupt.json').write_text('{broken', encoding='utf-8')
    open_new(page, live_server)
    expect(page.locator('#store-errors')).to_contain_text('corrupt.json')
    page.locator('#source-type').select_option('display_capture')
    page.locator('#add-source-button').click()
    page.locator('#save-button').click()
    expect(page.locator('#scene-error-message')).to_contain_text('monitor_id')
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
    expect(page.locator('#canvas-summary-fps')).not_to_have_text('')
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')


def test_verification_keeps_expected_actual_and_review_is_separate(page, live_server):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required for real media gates')
    open_new(page, live_server)
    add_browser(page)
    save(page)

    page.locator('#verify-button').click()
    open_card(page, '#verification-card')
    expect(page.locator('#verify-checks')).not_to_have_count(0)
    first_check = page.locator('#verify-checks .verification-check').first
    first_check.evaluate('el => el.open = true')
    expect(first_check).to_contain_text('Expected')
    expect(first_check).to_contain_text('Actual')

    verification_text = page.locator('#verify-checks').inner_text()
    open_card(page, '#review-card')
    page.locator('#review-seconds').fill('1')
    page.locator('#review-run-button').click()
    expect(page.locator('#review-state')).to_have_text('completed', timeout=20000)
    expect(page.locator('#review-checks')).to_contain_text('review.fps')
    assert page.locator('#verify-checks').inner_text() == verification_text
