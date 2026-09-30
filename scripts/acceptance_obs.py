r"""Opt-in local OBS acceptance. Never streams, deletes inputs, or touches C:\\Scripts.

Run with repo venv: python -m scripts.acceptance_obs setup|run|restore.
Re-running setup resumes an active session that failed before fixture preparation.
Requires operator approval, idle OBS, ffmpeg/ffprobe, and a separate node on 8785.
Run that node with an isolated runtime directory, for example:
STREAMOPS_NODE_DATA_DIR=.streamops/pr19-node
Install the optional graceful recovery task with:
.\scripts\devices\a-windows\install-obs-acceptance-recovery-task.ps1
Generated evidence stays under ignored .streamops/pr19-acceptance/.
"""
from copy import deepcopy
from datetime import datetime, timedelta, UTC
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from streamops.server.obs.client import ObsClient

ROOT = Path(__file__).resolve().parents[1] / '.streamops' / 'pr19-acceptance'
BASELINE = ROOT / 'baseline.json'
BASE = 'http://127.0.0.1:8785/api/v1/'
ACCEPTANCE_SCHEMA_VERSION = 2
DEFAULT_RECOVERY_TASK = 'StreamOps PR19 Close Idle OBS'
RECOVERY_WORKER = (
    Path(__file__).resolve().parent
    / 'devices'
    / 'a-windows'
    / 'invoke-obs-acceptance-recovery.ps1'
)
RECOVERY_REQUEST_TTL_SECONDS = 60
CONVERGENCE_TIMEOUT_SECONDS = 30
SHUTDOWN_TIMEOUT_SECONDS = 20
POLL_SECONDS = 0.5
LEGACY_RECOVERY_ERROR = (
    'Legacy acceptance session cannot be recovered automatically because '
    'no complete pre-mutation process identity is available. '
    'Operator cleanup is required.'
)


def write(name, data):
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / name
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
        encoding='utf-8',
    )
    os.replace(temporary, target)


def api(path, method='GET', payload=None, expected=200):
    request = Request(BASE+path, method=method, data=json.dumps(payload).encode() if payload is not None else None, headers={'Content-Type':'application/json'})
    try:
        with urlopen(request, timeout=90) as response:
            code, data = response.status, response.read()
    except HTTPError as exc:
        code, data = exc.code, exc.read()
    assert code == expected, (path, code, data.decode()[:3000])
    return json.loads(data) if data else None


def _timestamp():
    return datetime.now(UTC).isoformat().replace('+00:00', 'Z')


def _reconnect(client):
    client.close()
    client.connect()


def _recovery_task_arguments():
    request_path = ROOT / 'recovery-request.json'
    result_path = ROOT / 'recovery-result.json'
    return (
        '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden '
        '-ExecutionPolicy Bypass '
        f'-File "{RECOVERY_WORKER}" '
        f'-RequestPath "{request_path}" '
        f'-ResultPath "{result_path}"'
    )


def _same_windows_user(first, second):
    def account_name(value):
        return str(value or '').replace('/', '\\').rsplit('\\', 1)[-1].casefold()

    return bool(account_name(first)) and account_name(first) == account_name(second)


def validate_recovery_task():
    task_name = os.environ.get(
        'STREAMOPS_ACCEPTANCE_OBS_RECOVERY_TASK', DEFAULT_RECOVERY_TASK
    )
    powershell = shutil.which('powershell.exe') or shutil.which('powershell')
    if not powershell:
        raise RuntimeError('Windows PowerShell is required to validate OBS recovery.')
    script = (
        "$task=Get-ScheduledTask -TaskName $env:STREAMOPS_RECOVERY_TASK -ErrorAction Stop;"
        "$action=@($task.Actions);"
        "if($action.Count -ne 1){throw 'Recovery task must have exactly one action'};"
        "[pscustomobject]@{Name=$task.TaskName;State=[string]$task.State;"
        "LogonType=[string]$task.Principal.LogonType;"
        "RunLevel=[string]$task.Principal.RunLevel;UserId=$task.Principal.UserId;"
        "InteractiveUser=(Get-CimInstance Win32_ComputerSystem).UserName;"
        "TriggerCount=@($task.Triggers|Where-Object{$_ -ne $null}).Count;"
        "Execute=$action[0].Execute;Arguments=$action[0].Arguments;"
        "WorkingDirectory=$action[0].WorkingDirectory}|ConvertTo-Json -Compress"
    )
    env = os.environ.copy()
    env['STREAMOPS_RECOVERY_TASK'] = task_name
    result = subprocess.run(
        [powershell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    if result.returncode:
        raise RuntimeError(
            f"Acceptance OBS recovery task {task_name!r} is unavailable: "
            f"{result.stderr.strip() or result.stdout.strip()}. Run "
            '.\\scripts\\devices\\a-windows\\install-obs-acceptance-recovery-task.ps1.'
        )
    try:
        task = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('Acceptance OBS recovery task inspection was unreadable.') from exc
    arguments = str(task.get('Arguments') or '')
    expected_arguments = _recovery_task_arguments()
    expected_working_directory = str(Path(__file__).resolve().parents[1])
    if (
        task.get('Name') != task_name
        or task.get('LogonType') != 'Interactive'
        or task.get('RunLevel') != 'Limited'
        or task.get('TriggerCount') != 0
        or not _same_windows_user(task.get('UserId'), task.get('InteractiveUser'))
        or Path(str(task.get('Execute') or '')).name.lower() != 'powershell.exe'
        or ' '.join(arguments.split()) != ' '.join(expected_arguments.split())
        or str(task.get('WorkingDirectory') or '').casefold()
        != expected_working_directory.casefold()
    ):
        raise RuntimeError(
            'Acceptance OBS recovery task does not match the checked-in, '
            'interactive PID-bound definition. Run '
            '.\\scripts\\devices\\a-windows\\install-obs-acceptance-recovery-task.ps1.'
        )
    return task_name


def _read_matching_recovery_result(request_id):
    result_path = ROOT / 'recovery-result.json'
    if not result_path.is_file():
        return None
    try:
        result = json.loads(result_path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError):
        return None
    return result if result.get('request_id') == request_id else None


def _durable_recovery_mutation(state):
    safe = state.get('last_safe_runtime')
    if not isinstance(safe, dict):
        raise RuntimeError('OBS recovery has no pre-mutation idle snapshot.')
    mutation = safe.get('mutation')
    if not isinstance(mutation, str) or not mutation:
        raise RuntimeError('OBS recovery snapshot has no mutation provenance.')
    expected_step = mutation + '_requested'
    if state.get('setup_step') != expected_step:
        raise RuntimeError(
            'OBS recovery provenance is inconsistent: '
            f"setup_step={state.get('setup_step')!r}, mutation={mutation!r}."
        )
    return mutation


def _write_recovery_request(state, safe, process, *, mutation, recovery_key):
    request_id = uuid.uuid4().hex
    created = datetime.now(UTC)
    identity = {
        'pid': process.get('pid'),
        'started_at': process.get('started_at'),
        'session_id': process.get('session_id'),
        'active_console_session_id': process.get('active_console_session_id'),
        'executable_path': process.get('executable_path'),
    }
    if not all(identity.get(key) is not None for key in identity):
        raise RuntimeError('OBS recovery requires a complete process identity.')
    request = {
        'schema_version': 1,
        'request_id': request_id,
        'session_id': state.get('session_id'),
        'mutation': mutation,
        'recovery_key': recovery_key,
        'created_at': created.isoformat().replace('+00:00', 'Z'),
        'expires_at': (created + timedelta(seconds=RECOVERY_REQUEST_TTL_SECONDS))
        .isoformat()
        .replace('+00:00', 'Z'),
        'expected_process': identity,
        'idle_snapshot': {
            'streaming': safe.get('streaming'),
            'recording': safe.get('recording'),
            'observed_at': safe.get('observed_at'),
        },
    }
    write('recovery-request.json', request)
    return request


def recover_not_ready(client, state, *, mutation=None):
    status = api('obs/process/status')
    if status['state'] == 'READY':
        _reconnect(client)
        return status
    if status['state'] != 'RUNNING_NO_WEBSOCKET':
        raise RuntimeError(
            f"OBS recovery requires RUNNING_NO_WEBSOCKET, got {status['state']}."
        )

    safe = state.get('last_safe_runtime')
    required_snapshot_fields = (
        'mutation',
        'pid',
        'started_at',
        'session_id',
        'active_console_session_id',
        'executable_path',
        'observed_at',
    )
    if (
        not isinstance(safe, dict)
        or any(safe.get(field) is None for field in required_snapshot_fields)
    ):
        raise RuntimeError(LEGACY_RECOVERY_ERROR)

    durable_mutation = _durable_recovery_mutation(state)
    if mutation is not None and mutation != durable_mutation:
        raise RuntimeError(
            f'OBS recovery mutation {mutation!r} does not match durable '
            f'provenance {durable_mutation!r}.'
        )
    mutation = durable_mutation
    if safe.get('streaming') is not False or safe.get('recording') is not False:
        raise RuntimeError('OBS was not proven idle immediately before the mutation.')

    process = status.get('process') or {}
    if (
        not process.get('interactive')
        or process.get('session_id') != process.get('active_console_session_id')
    ):
        raise RuntimeError('OBS recovery requires the active interactive Windows session.')
    if safe.get('pid') != process.get('pid'):
        raise RuntimeError('OBS PID changed after the acceptance mutation; recovery refused.')
    if safe.get('started_at') != process.get('started_at'):
        raise RuntimeError(
            'OBS process start time changed after the acceptance mutation; recovery refused.'
        )
    if safe.get('session_id') != process.get('session_id'):
        raise RuntimeError(
            'OBS Windows session changed after the acceptance mutation; recovery refused.'
        )
    if safe.get('active_console_session_id') != process.get('active_console_session_id'):
        raise RuntimeError(
            'OBS active console session changed after the acceptance mutation; recovery refused.'
        )
    if safe.get('executable_path') != process.get('executable_path'):
        raise RuntimeError(
            'OBS executable changed after the acceptance mutation; recovery refused.'
        )

    recovery_key = (
        f"{mutation}:{safe['observed_at']}:{safe['pid']}:{safe['started_at']}"
    )
    attempts = state.setdefault('recovery_attempts', [])
    if any(item.get('recovery_key') == recovery_key for item in attempts):
        raise RuntimeError(f'OBS recovery was already attempted for {mutation}.')
    task_name = validate_recovery_task()
    request = _write_recovery_request(
        state, safe, process, mutation=mutation, recovery_key=recovery_key
    )
    attempt = {
        'mutation': mutation,
        'recovery_key': recovery_key,
        'request_id': request['request_id'],
        'task_name': task_name,
        'pid': process.get('pid'),
        'process_started_at': process.get('started_at'),
        'process_session_id': process.get('session_id'),
        'started_at': _timestamp(),
        'status': 'closing',
    }
    attempts.append(attempt)
    state['setup_state'] = 'recovering'
    write('baseline.json', state)
    write('setup-recovery.json', attempt)

    run = subprocess.run(
        ['schtasks.exe', '/Run', '/TN', task_name],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if run.returncode:
        attempt['status'] = 'task_failed'
        attempt['error'] = run.stderr.strip() or run.stdout.strip()
        write('setup-recovery.json', attempt)
        write('baseline.json', state)
        raise RuntimeError(f"Could not start graceful OBS recovery task: {attempt['error']}")

    deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        task_result = _read_matching_recovery_result(request['request_id'])
        if task_result and task_result.get('status') == 'refused':
            attempt['status'] = 'task_refused'
            attempt['error'] = task_result.get('error') or 'Recovery task refused the request.'
            write('setup-recovery.json', attempt)
            write('baseline.json', state)
            raise RuntimeError(f"Graceful OBS recovery was refused: {attempt['error']}")
        current = api('obs/process/status')
        if current['state'] == 'STOPPED':
            break
        time.sleep(POLL_SECONDS)
    else:
        attempt['status'] = 'graceful_close_timeout'
        attempt['error'] = 'OBS did not exit after CloseMainWindow; no force-kill was used.'
        write('setup-recovery.json', attempt)
        write('baseline.json', state)
        raise RuntimeError(attempt['error'])

    try:
        started = api('obs/process/start', 'POST')
        if started['state'] != 'READY':
            raise RuntimeError(
                f"OBS recovery start did not reach READY: {started['state']}."
            )
    except Exception as exc:
        attempt['status'] = 'start_failed'
        attempt['error'] = str(exc)
        write('setup-recovery.json', attempt)
        write('baseline.json', state)
        raise
    _reconnect(client)
    attempt['status'] = 'recovered'
    attempt['completed_at'] = _timestamp()
    attempt['new_pid'] = started.get('process', {}).get('pid')
    state['setup_state'] = 'preparing'
    write('setup-recovery.json', attempt)
    write('baseline.json', state)
    return started


def wait_for_convergence(
    client,
    state,
    *,
    mutation,
    expected_collection=None,
    expected_profile=None,
    allow_recovery=True,
):
    deadline = time.monotonic() + CONVERGENCE_TIMEOUT_SECONDS
    last_status = None
    last_error = None
    while time.monotonic() < deadline:
        last_status = api('obs/process/status')
        if last_status['state'] == 'READY':
            try:
                _reconnect(client)
                collection = client.get_scene_collection_list()['currentSceneCollectionName']
                profile = client.request('GetProfileList')['currentProfileName']
                if (
                    (expected_collection is None or collection == expected_collection)
                    and (expected_profile is None or profile == expected_profile)
                ):
                    return last_status
            except Exception as exc:
                last_error = exc
        time.sleep(POLL_SECONDS)
    if allow_recovery and last_status and last_status['state'] == 'RUNNING_NO_WEBSOCKET':
        recover_not_ready(client, state, mutation=mutation)
        return wait_for_convergence(
            client,
            state,
            mutation=mutation,
            expected_collection=expected_collection,
            expected_profile=expected_profile,
            allow_recovery=False,
        )
    detail = f': {last_error}' if last_error else ''
    raise RuntimeError(f'OBS did not converge after {mutation}{detail}')


def transition(
    client,
    state,
    *,
    mutation,
    action,
    expected_collection=None,
    expected_profile=None,
):
    status = api('obs/process/status')
    if (
        status['state'] != 'READY'
        or status['output']['streaming']
        or status['output']['recording']
    ):
        raise RuntimeError(f'OBS is not safely idle before {mutation}: {status}')
    process = status['process']
    state['last_safe_runtime'] = {
        'mutation': mutation,
        'pid': process['pid'],
        'started_at': process['started_at'],
        'session_id': process['session_id'],
        'active_console_session_id': process['active_console_session_id'],
        'executable_path': process['executable_path'],
        'streaming': status['output']['streaming'],
        'recording': status['output']['recording'],
        'observed_at': _timestamp(),
    }
    state['setup_step'] = mutation + '_requested'
    write('baseline.json', state)
    try:
        action()
    except Exception:
        after_action = api('obs/process/status')
        if after_action['state'] != 'RUNNING_NO_WEBSOCKET':
            raise
    result = wait_for_convergence(
        client,
        state,
        mutation=mutation,
        expected_collection=expected_collection,
        expected_profile=expected_profile,
    )
    state['setup_step'] = mutation + '_ready'
    write('baseline.json', state)
    return result


def idle(client):
    assert not client.get_stream_status()['outputActive'], 'Refusing active streaming'
    assert not client.get_record_status()['outputActive'], 'Refusing active recording'


def stop_owned_recording(client, *, timeout_seconds=15, poll_seconds=0.1):
    result = client.stop_record()
    deadline = time.monotonic() + timeout_seconds
    while client.get_record_status().get('outputActive'):
        if time.monotonic() >= deadline:
            raise RuntimeError('OBS did not finish stopping the acceptance recording.')
        time.sleep(poll_seconds)
    return result


def positive_profile_payload(state):
    return {
        'name': f"PR19 Motion + tone {state['session_id']}",
        'sources': [{
            'type': 'video_file',
            'name': 'Motion + tone',
            'settings': {
                'local_file': str(ROOT/'fixtures'/'motion-tone.mkv'),
                'looping': True,
                'restart_on_activate': True,
            },
            'audio': {'tracks': {'1': True, '2': True}},
            'verification': {
                'video_signal': True,
                'audio_signal': True,
                'sample_seconds': 1,
            },
        }],
    }


def write_manual_positive(state, profile, *, status, verification=None):
    evidence = {
        'session_id': state['session_id'],
        'profile_id': profile['id'],
        'profile_name': profile['name'],
        'test_collection': state['test_collection'],
        'test_profile': state['test_profile'],
        'fixture': profile['sources'][0]['settings']['local_file'],
        'status': status,
    }
    if verification is not None:
        evidence['verification'] = verification
    write('manual-positive.json', evidence)
    return evidence


def review_profile(path, profile, label):
    job = api(path+'/review', 'POST', {'seconds': 30}, 202)
    original = deepcopy(profile)
    changed = deepcopy(profile)
    changed['name'] = original['name'] + ' edited during review'
    api(path, 'PUT', changed)
    try:
        deadline = time.monotonic()+150
        while job['state'] in ('queued', 'running') and time.monotonic() < deadline:
            time.sleep(1)
            job = api('scene-reviews/'+job['job_id'])
        write(label+'.json', job)
        assert job['state'] == 'completed' and job['result']['status'] == 'PASS', job
        snapshot = json.loads(Path(job['result']['artifacts']['profile']).read_text(encoding='utf-8'))
        assert snapshot['name'] == original['name']
        return job['result']['artifacts']
    finally:
        # Review deliberately edits the persisted record after enqueueing. Always
        # put the exact pre-review payload back, including on timeout or failure.
        api(path, 'PUT', original)


def make_obs_ready():
    status = api('obs/process/status')
    if status['state'] == 'READY':
        return status
    if status['state'] == 'STOPPED':
        status = api('obs/process/start', 'POST')
    elif status['state'] == 'RUNNING_NO_WEBSOCKET':
        raise RuntimeError(
            'OBS is RUNNING_NO_WEBSOCKET; use the acceptance transaction recovery path.'
        )
    if status['state'] != 'READY':
        raise RuntimeError(f"OBS runtime must be READY for acceptance, got {status['state']}.")
    return status


def restore_obs_runtime(state):
    initial = state['initial_obs_runtime_state']
    current = api('obs/process/status')
    if initial == 'STOPPED':
        if current['state'] == 'READY':
            current = api('obs/process/stop', 'POST')
        if current['state'] != 'STOPPED':
            raise RuntimeError(f"Could not restore OBS runtime to STOPPED; got {current['state']}.")
    elif initial == 'READY':
        if current['state'] != 'READY':
            current = make_obs_ready()
    else:
        raise RuntimeError(f"Unsupported original OBS runtime state: {initial}.")
    return current


def select(client, state, test=True):
    idle(client)
    collection = state['test_collection'] if test else state['collection']
    profile = state['test_profile'] if test else state['profile']
    if client.get_scene_collection_list()['currentSceneCollectionName'] != collection:
        transition(
            client,
            state,
            mutation='select_test_collection' if test else 'restore_collection',
            action=lambda: client.request(
                'SetCurrentSceneCollection', {'sceneCollectionName': collection}
            ),
            expected_collection=collection,
        )
    if client.request('GetProfileList')['currentProfileName'] != profile:
        transition(
            client,
            state,
            mutation='select_test_profile' if test else 'restore_profile',
            action=lambda: client.request('SetCurrentProfile', {'profileName': profile}),
            expected_collection=collection,
            expected_profile=profile,
        )
    if not test and state['scene']:
        client.set_current_program_scene(state['scene'])


def _read_baseline():
    if not BASELINE.is_file():
        raise RuntimeError('No acceptance session exists. Run setup first.')
    try:
        state = json.loads(BASELINE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError('Acceptance baseline is unreadable; do not mutate OBS until it is inspected.') from exc
    required = {'session_id','active','collection','profile','scene','test_collection','test_profile','initial_obs_runtime_state'}
    if not isinstance(state, dict):
        raise RuntimeError(
            'Acceptance baseline is incompatible: expected a JSON object. '
            'Do not mutate OBS until it is inspected.'
        )
    missing = sorted(required.difference(state))
    if missing:
        raise RuntimeError(
            'Acceptance baseline is incompatible; missing fields: '
            + ', '.join(missing)
            + '. Do not mutate OBS until it is inspected.'
        )
    return state


def _restore(client, state):
    select(client, state, test=False)
    restored = {
        'collection': client.get_scene_collection_list()['currentSceneCollectionName'],
        'profile': client.request('GetProfileList')['currentProfileName'],
        'scene': client.get_current_program_scene(),
        'video': client.get_video_settings(),
    }
    expected = {key: state[key] for key in ('collection','profile','scene')}
    actual = {key: restored[key] for key in expected}
    if actual != expected:
        raise RuntimeError(f'OBS restore did not converge: expected {expected}, got {actual}')
    restored_runtime = restore_obs_runtime(state)
    restored['obs_runtime'] = restored_runtime
    completed = deepcopy(state)
    completed['active'] = False
    completed['restored_at'] = datetime.now(UTC).isoformat().replace('+00:00','Z')
    write('restored.json', restored)
    write(f"baseline-{completed['session_id']}.json", completed)
    write('baseline.json', completed)
    print('Original OBS collection/profile/scene restored. Test resources retained.', flush=True)


def setup(client, initial_obs_runtime_state):
    state = None
    if BASELINE.exists():
        previous = _read_baseline()
        if previous['active']:
            if previous.get('setup_state') in ('preparing', 'recovering'):
                state = previous
                print(
                    f"Resuming incomplete acceptance setup {state['session_id']}.",
                    flush=True,
                )
            else:
                raise RuntimeError(
                    f"Acceptance session {previous['session_id']} is already active or "
                    "was created by an older harness. Run it or restore it before setup."
                )
    current_runtime = api('obs/process/status')
    if state is not None and current_runtime['state'] == 'RUNNING_NO_WEBSOCKET':
        recover_not_ready(client, state)
        current_runtime = api('obs/process/status')
    if current_runtime['state'] != 'READY':
        raise RuntimeError(
            f"Acceptance setup requires OBS READY after preflight, got {current_runtime['state']}."
        )
    idle(client)
    if state is None and initial_obs_runtime_state not in ('READY', 'STOPPED'):
        raise RuntimeError(
            f"Acceptance can only preserve an initial READY or STOPPED OBS runtime; got {initial_obs_runtime_state}."
        )
    if state is None:
        stamp = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
        name = 'StreamOps PR19 Acceptance ' + stamp
        state = {
            'session_id': stamp,
            'active': True,
            'started_at': datetime.now(UTC).isoformat().replace('+00:00','Z'),
            'collection': client.get_scene_collection_list()['currentSceneCollectionName'],
            'profile': client.request('GetProfileList')['currentProfileName'],
            'scene': client.get_current_program_scene(),
            'video': client.get_video_settings(),
            'test_collection': name,
            'test_profile': name,
            'initial_obs_runtime_state': initial_obs_runtime_state,
            'setup_state': 'preparing',
            'setup_step': 'baseline_captured',
            'acceptance_schema_version': ACCEPTANCE_SCHEMA_VERSION,
            'recovery_attempts': [],
        }
        # Capture the current operator context for every new session before switching OBS.
        # Every mutation after this point is transactional: if setup fails, restore the
        # original collection/profile/scene/runtime before surfacing the failure.
        write('baseline.json', state)
    stamp = state['session_id']
    name = state['test_collection']
    try:
        collections = client.get_scene_collection_list()
        if name not in collections['sceneCollections']:
            transition(
                client,
                state,
                mutation='create_scene_collection',
                action=lambda: client.request(
                    'CreateSceneCollection', {'sceneCollectionName': name}
                ),
                expected_collection=name,
            )
        elif collections['currentSceneCollectionName'] != name:
            transition(
                client,
                state,
                mutation='select_test_collection',
                action=lambda: client.request(
                    'SetCurrentSceneCollection', {'sceneCollectionName': name}
                ),
                expected_collection=name,
            )
        state['setup_step'] = 'collection_ready'
        write('baseline.json', state)

        profiles = client.request('GetProfileList').get('profiles', [])
        if not isinstance(profiles, list) or not all(isinstance(profile, str) for profile in profiles):
            raise RuntimeError(f'Unexpected GetProfileList profiles payload: {profiles!r}')
        if name not in profiles:
            transition(
                client,
                state,
                mutation='create_obs_profile',
                action=lambda: client.request('CreateProfile', {'profileName': name}),
                expected_collection=name,
                expected_profile=name,
            )
        elif client.request('GetProfileList')['currentProfileName'] != name:
            transition(
                client,
                state,
                mutation='select_test_profile',
                action=lambda: client.request('SetCurrentProfile', {'profileName': name}),
                expected_collection=name,
                expected_profile=name,
            )
        state['setup_step'] = 'profile_ready'
        write('baseline.json', state)

        select(client, state)
        configure_recording(
            client, tracks=3, reload_via_profile=state['profile'], state=state
        )
        state['setup_step'] = 'recording_configured'
        write('baseline.json', state)
        fixtures = ROOT/'fixtures'
        fixtures.mkdir(exist_ok=True)
        for fixture_name, visual, audio in [
            ('motion-tone','testsrc2=size=640x360:rate=60','sine=frequency=440:sample_rate=48000'),
            ('black-silent','color=c=black:s=640x360:r=60','anullsrc=r=48000:cl=stereo'),
        ]:
            subprocess.run([
                shutil.which('ffmpeg'),'-y','-v','error','-f','lavfi','-i',visual,
                '-f','lavfi','-i',audio,'-t','5','-c:v','libx264','-preset','ultrafast',
                '-pix_fmt','yuv420p','-c:a','aac',str(fixtures/(fixture_name+'.mkv'))
            ], check=True)
        state['setup_step'] = 'fixtures_created'
        write('baseline.json', state)

        before = client.get_input_list()
        stored = api('scene-profiles')
        matches = [
            candidate for candidate in stored['profiles']
            if candidate['name'] == positive_profile_payload(state)['name']
        ]
        if len(matches) > 1:
            raise RuntimeError(
                'Multiple acceptance profiles match this session; refusing an ambiguous resume.'
            )
        acceptance_profile = matches[0] if matches else api(
            'scene-profiles', 'POST', positive_profile_payload(state), 201
        )
        save_left_obs_untouched = client.get_input_list() == before
        if not save_left_obs_untouched:
            raise RuntimeError('Saving the acceptance profile unexpectedly mutated OBS inputs.')
        state.update({
            'acceptance_profile_id': acceptance_profile['id'],
            'acceptance_profile_name': acceptance_profile['name'],
            'save_left_obs_untouched': True,
            'setup_state': 'prepared',
            'setup_step': 'prepared',
            'acceptance_schema_version': ACCEPTANCE_SCHEMA_VERSION,
        })
        write('tested-profile.json', acceptance_profile)
        write_manual_positive(state, acceptance_profile, status='READY_FOR_APPLY')
        write('baseline.json', state)
    except Exception as setup_exc:
        try:
            _restore(client, state)
        except Exception as restore_exc:
            write('setup-restore-failure.json', {
                'session_id': state['session_id'],
                'setup_error': str(setup_exc),
                'restore_error': str(restore_exc),
                'at': datetime.now(UTC).isoformat().replace('+00:00','Z'),
            })
            raise RuntimeError(
                f'Acceptance setup failed ({setup_exc}) and automatic restore also failed '
                f'({restore_exc}). Session remains active; inspect OBS before retrying.'
            ) from restore_exc
        raise
    print(
        f"Created isolated OBS acceptance session {stamp}; "
        f"positive profile: {state['acceptance_profile_name']} "
        f"({state['acceptance_profile_id']}).",
        flush=True,
    )

def configure_recording(client, tracks, *, reload_via_profile, state):
    idle(client)
    current_profile = client.request('GetProfileList')['currentProfileName']
    if not reload_via_profile or reload_via_profile == current_profile:
        raise RuntimeError(
            'Recording configuration reload requires a distinct fallback OBS profile.'
        )

    directory = ROOT/'recordings'
    directory.mkdir(parents=True, exist_ok=True)
    params = [('Output','Mode','Advanced'),('AdvOut','RecType','Standard'),('AdvOut','RecFormat2','mkv'),
              ('AdvOut','RecEncoder','obs_x264'),('AdvOut','RecTracks',str(tracks)),('AdvOut','RecFilePath',str(directory)),
              ('AdvOut','RecRescale','false')]
    for category, name, value in params:
        client.request('SetProfileParameter', {
            'parameterCategory':category,
            'parameterName':name,
            'parameterValue':value,
        })

    # SetProfileParameter persists config but OBS may keep the active output object
    # built from the previous settings. Bounce through the original profile so OBS
    # rebuilds outputs before G4 records media, then verify the reloaded config.
    transition(
        client,
        state,
        mutation='reload_recording_fallback_profile',
        action=lambda: client.request(
            'SetCurrentProfile', {'profileName': reload_via_profile}
        ),
        expected_collection=state['test_collection'],
        expected_profile=reload_via_profile,
    )
    transition(
        client,
        state,
        mutation='reload_recording_test_profile',
        action=lambda: client.request(
            'SetCurrentProfile', {'profileName': current_profile}
        ),
        expected_collection=state['test_collection'],
        expected_profile=current_profile,
    )

    mismatches = {}
    for category, name, expected in params:
        actual = client.get_profile_parameter(category, name)
        if str(actual) != expected:
            mismatches[f'{category}.{name}'] = {'expected': expected, 'actual': actual}
    if mismatches:
        raise RuntimeError(f'Reloaded OBS recording profile did not preserve expected settings: {mismatches}')


def restore_positive_fixture(client, state, profile):
    path = 'scene-profiles/'+profile['id']
    configure_recording(
        client, 3, reload_via_profile=state['profile'], state=state
    )
    restored = api(path, 'PUT', profile)
    api(path+'/apply', 'POST')
    api(path+'/activate', 'POST')
    time.sleep(2)
    verification = api(path+'/verify', 'POST')
    write('positive-restored-g3.json', verification)
    if verification['status'] != 'PASS':
        raise RuntimeError(
            f"Restored positive acceptance profile did not pass G3: {verification}"
        )
    write('tested-profile.json', restored)
    return write_manual_positive(
        state, restored, status='PASS', verification=verification
    )


def run(client):
    state = _read_baseline()
    if not state['active']:
        raise RuntimeError('No active acceptance session. Run setup before run.')
    select(client, state)
    results = []
    positive_profile = None
    def passed(name, detail=None):
        results.append({'case':name,'status':'PASS','detail':detail})
        write('matrix.json', results)
        print('PASS:', name, flush=True)
    try:
        configure_recording(
            client, 3, reload_via_profile=state['profile'], state=state
        )
        catalog = api('obs/source-catalog')
        inventory = api('obs/inventory')
        write('inventory.json', inventory)
        passed('Typed catalog / read-only native inventory', {'types':len(catalog['sources']), 'errors':inventory['errors']})
        required = {
            'acceptance_profile_id',
            'acceptance_profile_name',
            'save_left_obs_untouched',
            'setup_state',
        }
        missing = sorted(required.difference(state))
        if missing:
            raise RuntimeError(
                'Acceptance session was created by an older harness; missing fields: '
                + ', '.join(missing)
                + '. Restore it, then run setup again.'
            )
        if state['setup_state'] != 'prepared':
            raise RuntimeError(
                f"Acceptance setup is not prepared: {state['setup_state']!r}."
            )
        pid = state['acceptance_profile_id']
        path = 'scene-profiles/'+pid
        profile = api(path)
        if profile['name'] != state['acceptance_profile_name']:
            raise RuntimeError(
                'Acceptance profile no longer matches its baseline: '
                f"expected {state['acceptance_profile_name']!r}, got {profile['name']!r}."
            )
        positive_profile = deepcopy(profile)
        assert state['save_left_obs_untouched'] is True
        passed('Save leaves OBS untouched')
        assert api(path+'/apply','POST')['changed']
        assert not api(path+'/apply','POST')['changed']
        passed('Apply + second apply no-op')
        api(path+'/activate','POST')
        time.sleep(2)
        verification = api(path+'/verify','POST'); write('g3.json', verification)
        assert verification['status'] == 'PASS', verification
        passed('G2 structural + G3 real motion/tone')
        source = profile['sources'][0]; scene = profile['obs_scene_name']; name = source['obs_name']
        item = client.get_scene_item_list(scene)[0]['sceneItemId']
        client.set_scene_item_transform(scene,item,{'positionX':33})
        assert api(path+'/verify','POST')['status'] == 'FAIL'
        assert api(path+'/apply','POST')['changed']
        passed('Manual OBS transform drift detected and repaired')

        def review(label):
            passed(label, review_profile(path, profile, label))

        review('G4 30s AV tracks 1+2')
        profile['sources'][0]['audio']['tracks']['1']=False
        api(path,'PUT',profile); api(path+'/apply','POST')
        configure_recording(
            client, 2, reload_via_profile=state['profile'], state=state
        )
        review('G4 30s isolated track 2')
        profile['sources'][0]['audio']['muted']=True
        profile['sources'][0]['verification']['audio_signal']=False
        api(path,'PUT',profile); api(path+'/apply','POST')
        review('G4 30s video-only expected audio optional')

        # Active recording guard: only stop the recording started by this harness.
        client.start_record()
        try:
            assert not api(path+'/apply','POST')['changed']
            client.set_scene_item_transform(scene,item,{'positionX':44})
            api(path+'/apply','POST',expected=409)
            assert client.get_scene_item_transform(scene,item)['positionX']==44
        finally:
            stop_owned_recording(client)
        api(path+'/apply','POST')
        passed('Real recording guard: no-op allowed, mutation blocked')

        profile['sources'][0]['settings']['local_file']=str(ROOT/'fixtures'/'black-silent.mkv')
        profile['sources'][0]['audio']['muted']=False
        profile['sources'][0]['verification']['audio_signal']=True
        api(path,'PUT',profile); api(path+'/apply','POST'); time.sleep(2)
        negative=api(path+'/verify','POST'); write('black-silent.json',negative)
        assert any(c['status']=='FAIL' and c['id'].endswith('video_signal') for c in negative['checks'])
        assert any(c['status']=='FAIL' and c['id'].endswith('audio_signal') for c in negative['checks'])
        passed('Real effectively black and silent fixtures rejected')

        # Both inputs belong to the test collection. Never remove global inputs.
        a = f"PR19 Existing A {state['session_id']}"
        b = f"PR19 Existing B {state['session_id']}"
        fixture_scene = f"PR19 Existing fixtures {state['session_id']}"
        if fixture_scene not in {
            candidate['sceneName'] for candidate in client.get_scene_list()
        }:
            client.create_scene(fixture_scene)
        for target in (a,b):
            if not any(i['inputName']==target for i in client.get_input_list()):
                client.create_input(
                    fixture_scene,
                    target,
                    'color_source_v3',
                    {'color':4281554286,'width':640,'height':360},
                )
        existing=api('scene-profiles','POST',{
            'name': f"PR19 Existing binding {state['session_id']}",
            'sources':[{'type':'existing_video','settings':{'source_name':a}}],
        },201)
        epath='scene-profiles/'+existing['id']; escene=existing['obs_scene_name']
        api(epath+'/apply','POST')
        unrelated=client.create_scene_item(escene,name)
        existing['sources'][0]['settings']['source_name']=b
        api(epath,'PUT',existing); api(epath+'/apply','POST')
        assert a not in [i['sourceName'] for i in client.get_scene_item_list(escene)]
        existing['sources']=[]; api(epath,'PUT',existing); api(epath+'/apply','POST')
        items=client.get_scene_item_list(escene)
        assert len(items)==1 and items[0]['sceneItemId']==unrelated
        assert {a,b}.issubset({i['inputName'] for i in client.get_input_list()})
        assert api(epath+'/verify','POST')['status']=='WARN'
        passed('Existing A to B to removed; unowned item/global inputs preserved')
    except Exception as exc:
        results.append({'case':'Run failure','status':'FAIL','detail':str(exc)})
        write('matrix.json',results)
        raise
    finally:
        active_error = sys.exception()
        cleanup_errors = []
        if positive_profile is not None:
            try:
                restore_positive_fixture(client, state, positive_profile)
            except Exception as profile_restore_exc:
                cleanup_errors.append(profile_restore_exc)
                write('positive-profile-restore-failure.json', {
                    'session_id': state['session_id'],
                    'error': str(profile_restore_exc),
                    'at': datetime.now(UTC).isoformat().replace('+00:00','Z'),
                })
        try:
            _restore(client, state)
        except Exception as restore_exc:
            cleanup_errors.append(restore_exc)
            write('restore-failure.json', {
                'session_id': state['session_id'],
                'error': str(restore_exc),
                'at': datetime.now(UTC).isoformat().replace('+00:00','Z'),
            })
            print(f'RESTORE FAILED: {restore_exc}. Session remains active; run restore after fixing OBS.', flush=True)
        if cleanup_errors:
            if active_error is not None:
                raise ExceptionGroup(
                    'Acceptance run and cleanup failed.',
                    [active_error, *cleanup_errors],
                ) from active_error
            raise ExceptionGroup('Acceptance cleanup failed.', cleanup_errors)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['setup','run','restore'])
    action=parser.parse_args().action
    if action == 'setup':
        initial_runtime = api('obs/process/status')
        resumable = False
        # Preflight any existing session before changing OBS runtime state. This keeps
        # stale/legacy baseline artifacts from causing a STOPPED -> READY mutation
        # before setup aborts.
        if BASELINE.exists():
            previous = _read_baseline()
            if previous['active']:
                resumable = previous.get('setup_state') in ('preparing', 'recovering')
                if not resumable:
                    raise RuntimeError(
                        f"Acceptance session {previous['session_id']} is already active or "
                        "was created by an older harness. Run it or restore it before setup."
                    )
        if initial_runtime['state'] == 'STOPPED':
            make_obs_ready()
        elif initial_runtime['state'] == 'RUNNING_NO_WEBSOCKET' and resumable:
            pass
        elif initial_runtime['state'] != 'READY':
            raise RuntimeError(
                f"Acceptance setup requires OBS READY, STOPPED, or a resumable "
                f"RUNNING_NO_WEBSOCKET session; got {initial_runtime['state']}."
            )
    else:
        state = _read_baseline()
        if not state['active']:
            raise RuntimeError('No active acceptance session. Run setup first.')
        make_obs_ready()

    client=ObsClient.from_env()
    try:
        if action=='setup':
            setup(client, initial_runtime['state'])
        elif action=='run':
            run(client)
        else:
            _restore(client, state)
    finally:
        client.close()
