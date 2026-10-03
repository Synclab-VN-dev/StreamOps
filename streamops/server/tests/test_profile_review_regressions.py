"""Regressions from PR19's generic profile review (real validation/adapter)."""
from copy import deepcopy

import pytest
from types import SimpleNamespace

from streamops.server.errors import SceneProfileValidationError
from streamops.server.scene_profiles import normalize_profile
from streamops.server.obs.profile_scene import apply_profile, verify_profile
from streamops.server.tests.test_obs_scene import AudioFakeObsClient
from streamops.server.obs.profile_ownership import ProfileOwnership


@pytest.mark.parametrize('change', [
    {'settings': {'url': 'https://example.invalid', 'arbitrary': 1}},
    {'audio': {'volume_db': float('nan')}},
    {'audio': {'volume_db': 27}},
    {'audio': {'muted': 'false'}},
    {'verification': {'sample_seconds': -1}},
    {'verification': {'audio_threshold_db': float('inf')}},
])
def test_invalid_typed_source_rejected(change):
    source = {'type': 'browser_source', 'settings': {'url': 'https://example.invalid'}}
    source.update(change)
    with pytest.raises(SceneProfileValidationError):
        normalize_profile({'name': 'Invalid', 'sources': [source]})


def test_isolated_track_is_valid_desired_state():
    profile = normalize_profile({'name': 'Isolated', 'sources': [{
        'type': 'browser_source', 'settings': {'url': 'https://example.invalid'},
        'audio': {'tracks': {'2': True}},
    }]})
    obs = AudioFakeObsClient()
    apply_profile(profile, obs)
    result = verify_profile(profile, obs)
    assert result.status == 'PASS', [(c.id, c.status) for c in result.checks if c.status != 'PASS']


def test_existing_video_can_manage_audio_without_changing_its_input_kind():
    obs = AudioFakeObsClient()
    obs.create_scene('Operator')
    obs.create_input('Operator', 'OpenStream V8', 'openstream_phone_v7_source', {})
    profile = normalize_profile({'name': 'Camera audio isolation', 'sources': [{
        'type': 'existing_video',
        'settings': {'source_name': 'OpenStream V8'},
        'audio': {
            'enabled': False,
            'muted': True,
            'volume_db': 0,
            'sync_offset_ms': 0,
            'tracks': {str(index): False for index in range(1, 7)},
        },
    }]})

    apply_profile(profile, obs)

    assert obs.get_input_mute('OpenStream V8') is True
    assert obs.get_input_audio_tracks('OpenStream V8') == {
        str(index): False for index in range(1, 7)
    }
    result = verify_profile(profile, obs)
    assert result.status == 'PASS', [
        (check.id, check.status) for check in result.checks if check.status != 'PASS'
    ]


def test_video_signal_cannot_pass_without_a_frame():
    profile = normalize_profile({'name': 'Missing frame', 'sources': [{
        'type': 'browser_source', 'settings': {'url': 'https://example.invalid'},
        'verification': {'video_signal': True, 'sample_seconds': 0.5},
    }]})
    obs = AudioFakeObsClient()
    apply_profile(profile, obs)
    obs.get_source_screenshot = lambda *a, **k: b'invalid image'
    assert verify_profile(profile, obs, runtime=True).status == 'FAIL'


def test_existing_rebind_and_remove_survive_service_restart(tmp_path):
    obs = AudioFakeObsClient()
    obs.create_scene('Operator')
    obs.create_input('Operator', 'A', 'monitor_capture', {})
    obs.create_input('Operator', 'B', 'monitor_capture', {})
    profile = normalize_profile({'name':'Existing', 'sources':[{'type':'existing_video','settings':{'source_name':'A'}}]})
    def ownership():
        return ProfileOwnership(tmp_path).session(obs, profile)
    apply_profile(profile, obs, ownership=ownership())
    profile['sources'][0]['settings']['source_name'] = 'B'
    assert verify_profile(profile, obs, ownership=ownership()).status == 'FAIL'
    apply_profile(profile, obs, ownership=ownership())
    assert [i['sourceName'] for i in obs.get_scene_item_list(profile['obs_scene_name'])] == ['B']
    profile['sources'] = []
    apply_profile(profile, obs, ownership=ownership())
    assert obs.get_scene_item_list(profile['obs_scene_name']) == []
    assert {i['inputName'] for i in obs.inputs} == {'A','B'}


def test_corrupt_shapes_isolated_and_atomic_failure_preserves_saved(tmp_path, monkeypatch):
    import json
    from streamops.server.profile_store import SceneProfileStore
    from streamops.server.errors import SceneProfileStorageError
    store = SceneProfileStore(tmp_path)
    saved = store.create({'name':'Original'})
    for index, malformed in enumerate([[], {}, {'id':None,'name':'bad','schema_version':1,'sources':[],'canvas':{}}, {'id':saved['id'],'name':'bad','schema_version':1,'sources':[{'id':[]}],'canvas':{}}]):
        (tmp_path/f'bad-{index}.json').write_text(json.dumps(malformed),encoding='utf-8')
    assert len(store.list()['errors']) == 4
    def fail(*args): raise OSError('disk full')
    monkeypatch.setattr('streamops.server.profile_store.os.replace', fail)
    with pytest.raises(SceneProfileStorageError):
        store.update(saved['id'],{**saved,'name':'Not committed'})
    assert store.get(saved['id']) == saved


def test_review_snapshot_is_captured_at_enqueue_and_failure_has_report(tmp_path):
    from streamops.server.services.obs_scene import ObsSceneService
    from streamops.server.errors import SceneOperationError
    obs = AudioFakeObsClient()
    service = ObsSceneService(data_dir=tmp_path/'profiles', artifact_root=tmp_path/'artifacts',client_factory=lambda:obs)
    # Keep work queued to test edits that race with job execution.
    service._executor.shutdown()
    class Queue:
        def submit(self,*args): pass
        def shutdown(self,**kwargs): pass
    service._executor=Queue()
    saved=service.create_profile({'name':'Queued snapshot'})
    job=service.start_profile_review(saved['id'],seconds=1)
    service.update_profile(saved['id'],{**saved,'name':'Later edit'})
    with pytest.raises(SceneOperationError,match='already queued'):
        service.start_profile_review(saved['id'])
    service._run_profile_review(job.job_id)
    result=service.review_job(job.job_id)
    assert result.state=='failed'  # scene was never applied
    import json
    from pathlib import Path
    assert json.loads(Path(result.result['artifacts']['profile']).read_text(encoding='utf-8'))['name']=='Queued snapshot'
    assert Path(result.result['artifacts']['report']).exists()


def test_review_artifact_is_confined_to_its_job_directory(tmp_path):
    from streamops.server.errors import SceneReviewArtifactNotFoundError
    from streamops.server.services.obs_scene import ObsSceneService, ReviewJob

    service = ObsSceneService(data_dir=tmp_path/'profiles', artifact_root=tmp_path/'artifacts')
    job_dir = tmp_path/'artifacts'/'profile-id'/'job-id'
    job_dir.mkdir(parents=True)
    owned = job_dir/'preview.png'
    owned.write_bytes(b'preview')
    outside = tmp_path/'outside.json'
    outside.write_text('{}', encoding='utf-8')
    job = ReviewJob(
        job_id='job-id', scene='profile-id', state='completed',
        created_at='2026-10-01T00:00:00Z', updated_at='2026-10-01T00:00:01Z', seconds=1,
        result={'artifacts': {'preview': str(owned), 'outside': str(outside)}},
    )
    service._jobs[job.job_id] = job
    service._set_review_artifact_dir(job.job_id, job_dir)

    assert service.review_artifact('job-id', 'preview') == owned.resolve()
    for key in ('missing', '../preview', 'outside'):
        with pytest.raises(SceneReviewArtifactNotFoundError):
            service.review_artifact('job-id', key)
    service.close()


def test_probe_media_derives_missing_mkv_duration_from_video_packets(monkeypatch, tmp_path):
    from streamops.server.services import obs_scene

    media_path = tmp_path / 'sample.mkv'
    media_path.write_bytes(b'not-empty')
    monkeypatch.setattr(obs_scene.shutil, 'which', lambda name: 'ffprobe' if name == 'ffprobe' else None)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if '-show_packets' in args:
            return SimpleNamespace(
                returncode=0,
                stdout='{"packets":[{"pts_time":"0.000000","duration_time":"0.016667"},'
                       '{"pts_time":"29.983333","duration_time":"0.016667"}]}',
                stderr='',
            )
        return SimpleNamespace(
            returncode=0,
            stdout='{"streams":[{"codec_type":"video","avg_frame_rate":"60/1"},'
                   '{"codec_type":"audio"},{"codec_type":"audio"}],"format":{}}',
            stderr='',
        )

    monkeypatch.setattr(obs_scene.subprocess, 'run', fake_run)

    probe = obs_scene._probe_media(media_path)

    assert float(probe['format']['duration']) == pytest.approx(30.0, abs=0.001)
    assert len([stream for stream in probe['streams'] if stream['codec_type'] == 'audio']) == 2
    assert len(calls) == 2
    assert '-show_packets' in calls[1]


def test_probe_media_keeps_container_duration_without_packet_fallback(monkeypatch, tmp_path):
    from streamops.server.services import obs_scene

    media_path = tmp_path / 'sample.mkv'
    media_path.write_bytes(b'not-empty')
    monkeypatch.setattr(obs_scene.shutil, 'which', lambda name: 'ffprobe' if name == 'ffprobe' else None)

    def fake_run(args, **kwargs):
        assert '-show_packets' not in args
        return SimpleNamespace(
            returncode=0,
            stdout='{"streams":[{"codec_type":"video"}],"format":{"duration":"29.916667"}}',
            stderr='',
        )

    monkeypatch.setattr(obs_scene.subprocess, 'run', fake_run)

    probe = obs_scene._probe_media(media_path)

    assert probe['format']['duration'] == '29.916667'


def test_wait_for_stable_file_ignores_brief_muxer_idle_gap(monkeypatch, tmp_path):
    from streamops.server.services import obs_scene

    media_path = tmp_path / 'sample.mkv'
    media_path.write_bytes(b'partial')
    clock = {'now': 0.0, 'grew': False}

    monkeypatch.setattr(obs_scene.time, 'monotonic', lambda: clock['now'])

    def advance(seconds):
        clock['now'] += seconds
        if clock['now'] >= 0.5 and not clock['grew']:
            media_path.write_bytes(b'finalized recording')
            clock['grew'] = True

    monkeypatch.setattr(obs_scene.time, 'sleep', advance)

    obs_scene._wait_for_stable_file(
        media_path,
        timeout_seconds=3,
        poll_seconds=0.25,
        quiet_seconds=1,
    )

    assert clock['grew']
    assert clock['now'] >= 1.5
    assert media_path.read_bytes() == b'finalized recording'


def test_acceptance_waits_until_owned_recording_is_inactive(monkeypatch):
    from scripts import acceptance_obs

    clock = {'now': 0.0}

    class DelayedStopClient:
        def __init__(self):
            self.states = iter((True, True, False))
            self.stop_calls = 0

        def stop_record(self):
            self.stop_calls += 1
            return {'outputPath': 'sample.mkv'}

        def get_record_status(self):
            return {'outputActive': next(self.states)}

    client = DelayedStopClient()
    monkeypatch.setattr(acceptance_obs.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(acceptance_obs.time, 'sleep', lambda seconds: clock.__setitem__('now', clock['now'] + seconds))

    result = acceptance_obs.stop_owned_recording(client, timeout_seconds=1, poll_seconds=0.1)

    assert result == {'outputPath': 'sample.mkv'}
    assert client.stop_calls == 1
    assert clock['now'] == pytest.approx(0.2)


def test_production_review_waits_for_delayed_recording_shutdown(monkeypatch):
    from streamops.server.services import obs_scene

    clock = {'now': 0.0}

    class DelayedStopClient:
        def __init__(self):
            self.states = iter((True, True, True, False))
            self.stop_calls = 0

        def stop_record(self):
            self.stop_calls += 1
            return {'outputPath': 'sample.mkv'}

        def get_record_status(self):
            return {'outputActive': next(self.states)}

    client = DelayedStopClient()
    monkeypatch.setattr(obs_scene.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(obs_scene.time, 'sleep', lambda seconds: clock.__setitem__('now', clock['now'] + seconds))

    result = obs_scene._stop_recording_and_wait(client, timeout_seconds=1, poll_seconds=0.1)

    assert result == {'outputPath': 'sample.mkv'}
    assert client.stop_calls == 1
    assert clock['now'] == pytest.approx(0.2)


def test_production_review_recording_shutdown_timeout(monkeypatch):
    from streamops.server.services import obs_scene

    clock = {'now': 0.0}

    class StuckRecordingClient:
        stop_calls = 0

        def stop_record(self):
            self.stop_calls += 1
            return {'outputPath': 'sample.mkv'}

        def get_record_status(self):
            return {'outputActive': True}

    client = StuckRecordingClient()
    monkeypatch.setattr(obs_scene.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(obs_scene.time, 'sleep', lambda seconds: clock.__setitem__('now', clock['now'] + seconds))

    with pytest.raises(obs_scene.SceneOperationError, match='did not become inactive within 0.25 seconds'):
        obs_scene._stop_recording_and_wait(client, timeout_seconds=0.25, poll_seconds=0.1)

    assert client.stop_calls == 1


def test_production_review_cleanup_skips_stop_when_already_inactive():
    from streamops.server.services import obs_scene

    class InactiveClient:
        stop_calls = 0

        def stop_record(self):
            self.stop_calls += 1
            return {'outputPath': 'unexpected.mkv'}

        def get_record_status(self):
            return {'outputActive': False}

    client = InactiveClient()

    assert obs_scene._stop_recording_and_wait(client) == {}
    assert client.stop_calls == 0
