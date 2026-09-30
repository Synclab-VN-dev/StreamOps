import json
from types import SimpleNamespace

import pytest

from scripts import acceptance_obs


@pytest.mark.parametrize('resume', [False, True])
def test_setup_creates_session_specific_positive_profile_without_obs_mutation(tmp_path, monkeypatch, resume):
    monkeypatch.setattr(acceptance_obs, 'ROOT', tmp_path)
    monkeypatch.setattr(acceptance_obs, 'BASELINE', tmp_path / 'baseline.json')
    monkeypatch.setattr(acceptance_obs, 'configure_recording', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        acceptance_obs,
        'validate_recovery_task',
        lambda: pytest.fail('READY setup must not require a recovery task'),
    )
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
            'setup_step': 'baseline_captured',
            'acceptance_schema_version': 2,
            'recovery_attempts': [],
        }), encoding='utf-8')

    saved = []

    def fake_api(path, method='GET', payload=None, expected=200):
        if path == 'obs/process/status':
            return {
                'state': 'READY',
                'process': {
                    'pid': 10,
                    'started_at': '2026-09-30T00:00:00+07:00',
                    'session_id': 1,
                    'active_console_session_id': 1,
                    'interactive': True,
                    'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
                },
                'output': {'streaming': False, 'recording': False},
            }
        assert path == 'scene-profiles'
        if method == 'GET':
            return {'profiles': saved, 'errors': []}
        assert method == 'POST' and expected == 201
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

        def close(self):
            pass

        def connect(self):
            pass

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
    assert state['setup_step'] == 'prepared'
    assert state['acceptance_schema_version'] == 2
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


def test_recovery_mutation_comes_from_consistent_durable_state():
    state = {
        'setup_step': 'reload_recording_test_profile_requested',
        'last_safe_runtime': {'mutation': 'reload_recording_test_profile'},
    }

    assert (
        acceptance_obs._durable_recovery_mutation(state)
        == 'reload_recording_test_profile'
    )


def test_recovery_mutation_refuses_inconsistent_durable_state():
    state = {
        'setup_step': 'create_scene_collection_requested',
        'last_safe_runtime': {'mutation': 'restore_profile'},
    }

    with pytest.raises(RuntimeError, match='provenance is inconsistent'):
        acceptance_obs._durable_recovery_mutation(state)


def test_wait_for_convergence_polls_transient_not_ready_without_recovery(monkeypatch):
    statuses = iter([
        {'state': 'RUNNING_NO_WEBSOCKET'},
        {'state': 'READY'},
    ])
    recovered = []

    def fake_api(path, method='GET', payload=None, expected=200):
        assert path == 'obs/process/status'
        return next(statuses)

    class Client:
        def close(self):
            pass

        def connect(self):
            pass

        def get_scene_collection_list(self):
            return {'currentSceneCollectionName': 'Test'}

        def request(self, name):
            assert name == 'GetProfileList'
            return {'currentProfileName': 'Test'}

    monkeypatch.setattr(acceptance_obs, 'api', fake_api)
    monkeypatch.setattr(acceptance_obs.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(
        acceptance_obs,
        'recover_not_ready',
        lambda *args, **kwargs: recovered.append(kwargs),
    )

    result = acceptance_obs.wait_for_convergence(
        Client(), {}, mutation='create_scene_collection',
        expected_collection='Test', expected_profile='Test',
    )

    assert result['state'] == 'READY'
    assert recovered == []


def test_wait_for_convergence_recovers_prolonged_not_ready(monkeypatch):
    clock = {'now': 0.0, 'recovered': False}

    def fake_api(path, method='GET', payload=None, expected=200):
        assert path == 'obs/process/status'
        return {'state': 'READY' if clock['recovered'] else 'RUNNING_NO_WEBSOCKET'}

    class Client:
        def close(self):
            pass

        def connect(self):
            pass

        def get_scene_collection_list(self):
            return {'currentSceneCollectionName': 'Test'}

        def request(self, name):
            assert name == 'GetProfileList'
            return {'currentProfileName': 'Test'}

    monkeypatch.setattr(acceptance_obs, 'api', fake_api)
    monkeypatch.setattr(acceptance_obs, 'CONVERGENCE_TIMEOUT_SECONDS', 1)
    monkeypatch.setattr(acceptance_obs.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(
        acceptance_obs.time,
        'sleep',
        lambda seconds: clock.__setitem__('now', clock['now'] + seconds),
    )

    def recover(*args, **kwargs):
        clock['recovered'] = True

    monkeypatch.setattr(acceptance_obs, 'recover_not_ready', recover)

    result = acceptance_obs.wait_for_convergence(
        Client(), {}, mutation='create_scene_collection', expected_collection='Test'
    )

    assert result['state'] == 'READY'
    assert clock['recovered'] is True


def test_recover_not_ready_refuses_legacy_baseline_without_recovery_side_effects(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(acceptance_obs, 'ROOT', tmp_path)
    monkeypatch.setattr(acceptance_obs, 'BASELINE', tmp_path / 'baseline.json')
    state = {
        'session_id': 'legacy-session',
        'setup_state': 'preparing',
        'setup_step': 'create_scene_collection_requested',
        'test_collection': 'StreamOps PR19 Acceptance legacy-session',
        'last_safe_runtime': {
            'mutation': 'create_scene_collection',
            'streaming': False,
            'recording': False,
            'observed_at': '2026-09-29T00:00:00Z',
        },
        'recovery_attempts': [],
    }
    (tmp_path / 'setup-restore-failure.json').write_text(json.dumps({
        'session_id': 'legacy-session',
        'setup_error': 'GetProfileList failed (207): OBS is not ready.',
    }), encoding='utf-8')
    monkeypatch.setattr(acceptance_obs, 'api', lambda *args, **kwargs: {
        'state': 'RUNNING_NO_WEBSOCKET',
        'process': {
            'pid': 99,
            'interactive': True,
            'started_at': '2026-09-30T00:00:00+07:00',
            'session_id': 1,
            'active_console_session_id': 1,
            'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
        },
    })
    monkeypatch.setattr(
        acceptance_obs,
        'validate_recovery_task',
        lambda: pytest.fail('legacy recovery must not validate the recovery task'),
    )
    monkeypatch.setattr(
        acceptance_obs,
        '_write_recovery_request',
        lambda *args, **kwargs: pytest.fail('legacy recovery must not write a request'),
    )
    monkeypatch.setattr(
        acceptance_obs.subprocess,
        'run',
        lambda *args, **kwargs: pytest.fail('legacy recovery must not run schtasks'),
    )

    with pytest.raises(
        RuntimeError,
        match='Legacy acceptance session cannot be recovered automatically',
    ):
        acceptance_obs.recover_not_ready(
            object(), state, mutation='create_scene_collection'
        )

    assert state['recovery_attempts'] == []
    assert not (tmp_path / 'recovery-request.json').exists()
    assert not (tmp_path / 'setup-recovery.json').exists()


def test_recover_not_ready_uses_graceful_task_before_lifecycle_start(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance_obs, 'ROOT', tmp_path)
    monkeypatch.setattr(acceptance_obs, 'BASELINE', tmp_path / 'baseline.json')
    state = {
        'session_id': 'session',
        'setup_state': 'preparing',
        'setup_step': 'create_scene_collection_requested',
        'last_safe_runtime': {
            'mutation': 'create_scene_collection',
            'pid': 50,
            'started_at': '2026-09-30T00:00:00+07:00',
            'session_id': 1,
            'active_console_session_id': 1,
            'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
            'streaming': False,
            'recording': False,
            'observed_at': '2026-09-30T00:00:00Z',
        },
        'recovery_attempts': [],
    }
    calls = []

    def fake_api(path, method='GET', payload=None, expected=200):
        calls.append((path, method))
        if path == 'obs/process/start':
            return {'state': 'READY', 'process': {'pid': 51}}
        if len([call for call in calls if call[0] == 'obs/process/status']) == 1:
            return {
                'state': 'RUNNING_NO_WEBSOCKET',
                'process': {
                    'pid': 50, 'interactive': True,
                    'started_at': '2026-09-30T00:00:00+07:00',
                    'session_id': 1, 'active_console_session_id': 1,
                    'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
                },
            }
        return {'state': 'STOPPED', 'process': {'running': False}}

    class Client:
        closes = 0
        connects = 0

        def close(self):
            self.closes += 1

        def connect(self):
            self.connects += 1

    task_calls = []
    monkeypatch.setattr(acceptance_obs, 'api', fake_api)
    monkeypatch.setattr(acceptance_obs, 'validate_recovery_task', lambda: 'Graceful task')
    monkeypatch.setattr(
        acceptance_obs.subprocess,
        'run',
        lambda args, **kwargs: task_calls.append(args) or SimpleNamespace(returncode=0, stdout='', stderr=''),
    )

    client = Client()
    result = acceptance_obs.recover_not_ready(
        client, state, mutation='create_scene_collection'
    )

    assert result['state'] == 'READY'
    assert task_calls == [['schtasks.exe', '/Run', '/TN', 'Graceful task']]
    assert calls[-1] == ('obs/process/start', 'POST')
    assert state['recovery_attempts'][0]['status'] == 'recovered'
    assert client.closes == client.connects == 1
    request = json.loads((tmp_path / 'recovery-request.json').read_text(encoding='utf-8'))
    assert request['mutation'] == 'create_scene_collection'
    assert request['expected_process']['pid'] == 50
    assert request['expected_process']['started_at'] == '2026-09-30T00:00:00+07:00'
    assert request['expected_process']['session_id'] == 1
    assert request['expected_process']['active_console_session_id'] == 1
    assert request['expected_process']['executable_path'] == (
        r'C:\Program Files\obs-studio\bin\64bit\obs64.exe'
    )
    assert request['idle_snapshot']['streaming'] is False
    assert request['idle_snapshot']['recording'] is False
    assert request['idle_snapshot']['observed_at'] == '2026-09-30T00:00:00Z'


def test_recover_not_ready_refuses_pid_change_without_closing(monkeypatch):
    state = {
        'session_id': 'session',
        'setup_state': 'preparing',
        'setup_step': 'create_scene_collection_requested',
        'last_safe_runtime': {
            'mutation': 'create_scene_collection',
            'pid': 50,
            'started_at': '2026-09-30T00:00:00+07:00',
            'session_id': 1,
            'active_console_session_id': 1,
            'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
            'streaming': False,
            'recording': False,
            'observed_at': '2026-09-30T00:00:00Z',
        },
    }
    monkeypatch.setattr(acceptance_obs, 'api', lambda *args, **kwargs: {
        'state': 'RUNNING_NO_WEBSOCKET',
        'process': {
            'pid': 99, 'interactive': True,
            'started_at': '2026-09-30T00:00:00+07:00',
            'session_id': 1, 'active_console_session_id': 1,
            'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
        },
    })
    monkeypatch.setattr(
        acceptance_obs.subprocess,
        'run',
        lambda *args, **kwargs: pytest.fail('recovery task must not run'),
    )

    with pytest.raises(RuntimeError, match='PID changed'):
        acceptance_obs.recover_not_ready(
            object(), state, mutation='create_scene_collection'
        )


def test_recover_not_ready_refuses_process_start_time_change_without_closing(monkeypatch):
    state = {
        'session_id': 'session',
        'setup_state': 'preparing',
        'setup_step': 'restore_profile_requested',
        'last_safe_runtime': {
            'mutation': 'restore_profile',
            'pid': 50,
            'started_at': '2026-09-30T00:00:00+07:00',
            'session_id': 1,
            'active_console_session_id': 1,
            'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
            'streaming': False,
            'recording': False,
            'observed_at': '2026-09-30T00:00:00Z',
        },
    }
    monkeypatch.setattr(acceptance_obs, 'api', lambda *args, **kwargs: {
        'state': 'RUNNING_NO_WEBSOCKET',
        'process': {
            'pid': 50,
            'started_at': '2026-09-30T00:00:01+07:00',
            'interactive': True,
            'session_id': 1,
            'active_console_session_id': 1,
            'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
        },
    })
    monkeypatch.setattr(
        acceptance_obs.subprocess,
        'run',
        lambda *args, **kwargs: pytest.fail('recovery task must not run'),
    )

    with pytest.raises(RuntimeError, match='start time changed'):
        acceptance_obs.recover_not_ready(object(), state, mutation='restore_profile')


def test_recover_not_ready_never_starts_after_graceful_close_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance_obs, 'ROOT', tmp_path)
    monkeypatch.setattr(acceptance_obs, 'BASELINE', tmp_path / 'baseline.json')
    state = {
        'session_id': 'session',
        'setup_state': 'preparing',
        'setup_step': 'create_scene_collection_requested',
        'last_safe_runtime': {
            'mutation': 'create_scene_collection',
            'pid': 50,
            'started_at': '2026-09-30T00:00:00+07:00',
            'session_id': 1,
            'active_console_session_id': 1,
            'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
            'streaming': False,
            'recording': False,
            'observed_at': '2026-09-30T00:00:00Z',
        },
    }
    clock = {'now': 0.0}
    api_calls = []

    def fake_api(path, method='GET', payload=None, expected=200):
        api_calls.append((path, method))
        assert path != 'obs/process/start'
        return {
            'state': 'RUNNING_NO_WEBSOCKET',
            'process': {
                'pid': 50, 'interactive': True,
                'started_at': '2026-09-30T00:00:00+07:00',
                'session_id': 1, 'active_console_session_id': 1,
                'executable_path': r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
            },
        }

    monkeypatch.setattr(acceptance_obs, 'api', fake_api)
    monkeypatch.setattr(acceptance_obs, 'validate_recovery_task', lambda: 'Graceful task')
    monkeypatch.setattr(acceptance_obs, 'SHUTDOWN_TIMEOUT_SECONDS', 1)
    monkeypatch.setattr(acceptance_obs.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(
        acceptance_obs.time,
        'sleep',
        lambda seconds: clock.__setitem__('now', clock['now'] + seconds),
    )
    monkeypatch.setattr(
        acceptance_obs.subprocess,
        'run',
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='', stderr=''),
    )

    with pytest.raises(RuntimeError, match='no force-kill'):
        acceptance_obs.recover_not_ready(
            object(), state, mutation='create_scene_collection'
        )

    assert ('obs/process/start', 'POST') not in api_calls
    assert state['recovery_attempts'][0]['status'] == 'graceful_close_timeout'


def test_validate_recovery_task_requires_checked_in_pid_bound_action(monkeypatch):
    task = {
        'Name': acceptance_obs.DEFAULT_RECOVERY_TASK,
        'State': 'Ready',
        'LogonType': 'Interactive',
        'RunLevel': 'Limited',
        'TriggerCount': 0,
        'UserId': 'huy',
        'InteractiveUser': r'DESKTOP\huy',
        'Execute': 'powershell.exe',
        'Arguments': acceptance_obs._recovery_task_arguments(),
        'WorkingDirectory': str(acceptance_obs.ROOT.parents[1]),
    }
    monkeypatch.setattr(acceptance_obs.shutil, 'which', lambda name: 'powershell.exe')
    monkeypatch.setattr(
        acceptance_obs.subprocess,
        'run',
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(task), stderr=''
        ),
    )

    assert acceptance_obs.validate_recovery_task() == acceptance_obs.DEFAULT_RECOVERY_TASK

    task['Arguments'] = '-Command "(Get-Process obs64).CloseMainWindow()"'
    with pytest.raises(RuntimeError, match='PID-bound definition'):
        acceptance_obs.validate_recovery_task()


@pytest.mark.skipif(acceptance_obs.sys.platform != 'win32', reason='Windows task worker')
def test_recovery_worker_refuses_expired_request_without_process_mutation(tmp_path):
    request_path = tmp_path / 'request.json'
    result_path = tmp_path / 'result.json'
    request_path.write_text(
        json.dumps({
            'schema_version': 1,
            'request_id': 'expired-request',
            'expires_at': '2000-01-01T00:00:00Z',
        }),
        encoding='utf-8',
    )
    powershell = acceptance_obs.shutil.which('powershell.exe')
    assert powershell is not None

    result = acceptance_obs.subprocess.run(
        [
            powershell,
            '-NoLogo',
            '-NoProfile',
            '-NonInteractive',
            '-File',
            str(acceptance_obs.RECOVERY_WORKER),
            '-RequestPath',
            str(request_path),
            '-ResultPath',
            str(result_path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 1
    evidence = json.loads(result_path.read_text(encoding='utf-8-sig'))
    assert evidence['request_id'] == 'expired-request'
    assert evidence['status'] == 'refused'
    assert 'expired' in evidence['error'].lower()


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
