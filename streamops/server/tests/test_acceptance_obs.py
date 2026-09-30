import json

import pytest

from scripts import acceptance_obs


@pytest.mark.parametrize('resume', [False, True])
def test_setup_creates_session_specific_positive_profile_without_obs_mutation(tmp_path, monkeypatch, resume):
    monkeypatch.setattr(acceptance_obs, 'ROOT', tmp_path)
    monkeypatch.setattr(acceptance_obs, 'BASELINE', tmp_path / 'baseline.json')
    monkeypatch.setattr(acceptance_obs, 'configure_recording', lambda *args, **kwargs: None)
    monkeypatch.setattr(acceptance_obs.subprocess, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(acceptance_obs.time, 'sleep', lambda seconds: None)

    if resume:
        (tmp_path / 'baseline.json').write_text(json.dumps({
            'session_id': 'existing-session',
            'active': True,
            'started_at': '2026-09-30T00:00:00Z',
            'collection': 'Operator collection',
            'profile': 'Operator profile',
            'scene': 'Operator scene',
            'video': {'baseWidth': 1920, 'baseHeight': 1080},
            'test_collection': 'StreamOps PR19 Acceptance existing-session',
            'test_profile': 'StreamOps PR19 Acceptance existing-session',
            'initial_obs_runtime_state': 'READY',
            'setup_state': 'preparing',
        }), encoding='utf-8')

    saved = []

    def fake_api(path, method='GET', payload=None, expected=200):
        assert path == 'scene-profiles'
        assert method == 'POST'
        assert expected == 201
        profile = {
            **payload,
            'id': 'positive-id',
            'obs_scene_name': 'StreamOps - positive-id',
        }
        profile['sources'][0] = {
            **profile['sources'][0],
            'id': 'source-id',
            'obs_name': 'StreamOps positive-id source-id',
        }
        saved.append(profile)
        return profile

    monkeypatch.setattr(acceptance_obs, 'api', fake_api)

    class Client:
        collection = 'Operator collection'
        profile = 'Operator profile'
        collections = ['Operator collection']
        profiles = ['Operator profile']

        def get_stream_status(self):
            return {'outputActive': False}

        def get_record_status(self):
            return {'outputActive': False}

        def get_scene_collection_list(self):
            return {
                'currentSceneCollectionName': self.collection,
                'sceneCollections': self.collections,
            }

        def get_current_program_scene(self):
            return 'Operator scene'

        def get_video_settings(self):
            return {'baseWidth': 1920, 'baseHeight': 1080}

        def get_input_list(self):
            return [{'inputName': 'Operator input'}]

        def request(self, name, payload=None):
            payload = payload or {}
            if name == 'GetProfileList':
                return {'currentProfileName': self.profile, 'profiles': self.profiles}
            if name == 'CreateSceneCollection':
                self.collections.append(payload['sceneCollectionName'])
                self.collection = payload['sceneCollectionName']
                return {}
            if name == 'CreateProfile':
                self.profiles.append(payload['profileName'])
                self.profile = payload['profileName']
                return {}
            if name == 'SetCurrentSceneCollection':
                self.collection = payload['sceneCollectionName']
                return {}
            if name == 'SetCurrentProfile':
                self.profile = payload['profileName']
                return {}
            raise AssertionError(name)

    acceptance_obs.setup(Client(), 'READY')

    state = json.loads((tmp_path / 'baseline.json').read_text(encoding='utf-8'))
    assert state['acceptance_profile_id'] == 'positive-id'
    assert state['acceptance_profile_name'] == saved[0]['name']
    assert state['session_id'] in saved[0]['name']
    if resume:
        assert state['session_id'] == 'existing-session'
    assert state['save_left_obs_untouched'] is True
    assert state['setup_state'] == 'prepared'
    evidence = json.loads((tmp_path / 'manual-positive.json').read_text(encoding='utf-8'))
    assert evidence['profile_id'] == 'positive-id'
    assert evidence['status'] == 'READY_FOR_APPLY'


def test_setup_does_not_resume_unknown_active_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance_obs, 'ROOT', tmp_path)
    monkeypatch.setattr(acceptance_obs, 'BASELINE', tmp_path / 'baseline.json')
    (tmp_path / 'baseline.json').write_text(json.dumps({
        'session_id': 'legacy-session',
        'active': True,
        'collection': 'Operator collection',
        'profile': 'Operator profile',
        'scene': 'Operator scene',
        'test_collection': 'Legacy test collection',
        'test_profile': 'Legacy test profile',
        'initial_obs_runtime_state': 'READY',
    }), encoding='utf-8')

    class IdleClient:
        def get_stream_status(self):
            return {'outputActive': False}

        def get_record_status(self):
            return {'outputActive': False}

    with pytest.raises(RuntimeError, match='older harness'):
        acceptance_obs.setup(IdleClient(), 'READY')


def test_review_restores_saved_profile_when_result_fails(monkeypatch):
    profile = {'id': 'profile-id', 'name': 'Positive fixture', 'sources': []}
    puts = []

    def fake_api(path, method='GET', payload=None, expected=200):
        if path.endswith('/review'):
            return {'job_id': 'job-id', 'state': 'completed', 'result': {'status': 'FAIL'}}
        if method == 'PUT':
            puts.append(payload)
            return payload
        raise AssertionError((path, method))

    monkeypatch.setattr(acceptance_obs, 'api', fake_api)
    monkeypatch.setattr(acceptance_obs, 'write', lambda *args: None)

    with pytest.raises(AssertionError):
        acceptance_obs.review_profile('scene-profiles/profile-id', profile, 'review')

    assert puts[0]['name'].endswith(' edited during review')
    assert puts[-1] == profile


def test_restore_positive_fixture_replaces_negative_payload_and_verifies(monkeypatch):
    state = {'session_id': 'session', 'profile': 'Operator profile', 'test_collection': 'Test', 'test_profile': 'Test'}
    positive = {
        'id': 'positive-id',
        'name': 'PR19 Motion + tone session',
        'sources': [{'settings': {'local_file': 'motion-tone.mkv'}}],
    }
    calls = []
    written = {}

    def fake_api(path, method='GET', payload=None, expected=200):
        calls.append((path, method, payload))
        if method == 'PUT':
            return payload
        if path.endswith('/verify'):
            return {'status': 'PASS', 'checks': []}
        return {'changed': True}

    monkeypatch.setattr(acceptance_obs, 'api', fake_api)
    monkeypatch.setattr(acceptance_obs, 'configure_recording', lambda *args, **kwargs: None)
    monkeypatch.setattr(acceptance_obs.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(acceptance_obs, 'write', lambda name, data: written.__setitem__(name, data))

    evidence = acceptance_obs.restore_positive_fixture(object(), state, positive)

    assert calls[0] == ('scene-profiles/positive-id', 'PUT', positive)
    assert [call[:2] for call in calls[1:]] == [
        ('scene-profiles/positive-id/apply', 'POST'),
        ('scene-profiles/positive-id/activate', 'POST'),
        ('scene-profiles/positive-id/verify', 'POST'),
    ]
    assert evidence['status'] == 'PASS'
    assert written['manual-positive.json']['profile_name'] == positive['name']
