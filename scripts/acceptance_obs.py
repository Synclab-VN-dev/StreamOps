"""Opt-in local OBS acceptance. Never streams, deletes inputs, or touches C:\\Scripts.

Run with repo venv: python -m scripts.acceptance_obs setup|run|restore.
Requires operator approval, idle OBS, ffmpeg/ffprobe, and a separate node on 8785.
Run that node with an isolated runtime directory, for example:
STREAMOPS_NODE_DATA_DIR=.streamops/pr19-node
Generated evidence stays under ignored .streamops/pr19-acceptance/.
"""
from copy import deepcopy
from datetime import datetime, UTC
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from streamops.server.obs.client import ObsClient
from streamops.server.errors import ObsRequestError

ROOT = Path(__file__).resolve().parents[1] / '.streamops' / 'pr19-acceptance'
BASELINE = ROOT / 'baseline.json'
BASE = 'http://127.0.0.1:8785/api/v1/'


def write(name, data):
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT/name).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def api(path, method='GET', payload=None, expected=200):
    request = Request(BASE+path, method=method, data=json.dumps(payload).encode() if payload is not None else None, headers={'Content-Type':'application/json'})
    try:
        with urlopen(request, timeout=90) as response:
            code, data = response.status, response.read()
    except HTTPError as exc:
        code, data = exc.code, exc.read()
    assert code == expected, (path, code, data.decode()[:3000])
    return json.loads(data) if data else None


def idle(client):
    assert not client.get_stream_status()['outputActive'], 'Refusing active streaming'
    assert not client.get_record_status()['outputActive'], 'Refusing active recording'


def select(client, state, test=True):
    idle(client)
    collection = state['test_collection'] if test else state['collection']
    profile = state['test_profile'] if test else state['profile']
    if client.get_scene_collection_list()['currentSceneCollectionName'] != collection:
        client.request('SetCurrentSceneCollection', {'sceneCollectionName':collection})
        time.sleep(2)
    if client.request('GetProfileList')['currentProfileName'] != profile:
        client.request('SetCurrentProfile', {'profileName':profile})
        time.sleep(2)
    if not test and state['scene']:
        client.set_current_program_scene(state['scene'])


def _read_baseline():
    if not BASELINE.is_file():
        raise RuntimeError('No acceptance session exists. Run setup first.')
    try:
        state = json.loads(BASELINE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError('Acceptance baseline is unreadable; do not mutate OBS until it is inspected.') from exc
    required = {'session_id','active','collection','profile','scene','test_collection','test_profile'}
    if not isinstance(state, dict) or not required.issubset(state):
        raise RuntimeError('Acceptance baseline is incomplete; do not mutate OBS until it is inspected.')
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
    completed = deepcopy(state)
    completed['active'] = False
    completed['restored_at'] = datetime.now(UTC).isoformat().replace('+00:00','Z')
    write('restored.json', restored)
    write(f"baseline-{completed['session_id']}.json", completed)
    write('baseline.json', completed)
    print('Original OBS collection/profile/scene restored. Test resources retained.', flush=True)


def setup(client):
    idle(client)
    if BASELINE.exists():
        previous = _read_baseline()
        if previous['active']:
            raise RuntimeError(
                f"Acceptance session {previous['session_id']} is still active. "
                "Run restore before starting a new session."
            )
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
    }
    # Capture the current operator context for every new session before switching OBS.
    write('baseline.json', state)
    if name not in client.get_scene_collection_list()['sceneCollections']:
        client.request('CreateSceneCollection', {'sceneCollectionName':name})
        time.sleep(2)
    if name not in [p['profileName'] for p in client.request('GetProfileList')['profiles']]:
        client.request('CreateProfile', {'profileName':name})
        time.sleep(2)
    select(client, state)
    configure_recording(client, tracks=3)
    fixtures = ROOT/'fixtures'
    fixtures.mkdir(exist_ok=True)
    for name, visual, audio in [('motion-tone','testsrc2=size=640x360:rate=60','sine=frequency=440:sample_rate=48000'),
                                 ('black-silent','color=c=black:s=640x360:r=60','anullsrc=r=48000:cl=stereo')]:
        subprocess.run([shutil.which('ffmpeg'),'-y','-v','error','-f','lavfi','-i',visual,'-f','lavfi','-i',audio,
                        '-t','5','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(fixtures/(name+'.mkv'))], check=True)
    print(f"Created isolated OBS acceptance session {stamp}.", flush=True)

def configure_recording(client, tracks):
    directory = ROOT/'recordings'
    directory.mkdir(parents=True, exist_ok=True)
    params = [('Output','Mode','Advanced'),('AdvOut','RecType','Standard'),('AdvOut','RecFormat2','mkv'),
              ('AdvOut','RecEncoder','obs_x264'),('AdvOut','RecTracks',str(tracks)),('AdvOut','RecFilePath',str(directory)),
              ('AdvOut','RecRescale','false')]
    for category, name, value in params:
        client.request('SetProfileParameter', {'parameterCategory':category,'parameterName':name,'parameterValue':value})


def run(client):
    state = _read_baseline()
    if not state['active']:
        raise RuntimeError('No active acceptance session. Run setup before run.')
    select(client, state)
    results = []
    def passed(name, detail=None):
        results.append({'case':name,'status':'PASS','detail':detail})
        write('matrix.json', results)
        print('PASS:', name, flush=True)
    try:
        configure_recording(client, 3)
        catalog = api('obs/source-catalog')
        inventory = api('obs/inventory')
        write('inventory.json', inventory)
        passed('Typed catalog / read-only native inventory', {'types':len(catalog['sources']), 'errors':inventory['errors']})
        before = client.get_input_list()
        profile = api('scene-profiles','POST',{'name':'PR19 Motion + tone','sources':[{
            'type':'video_file','name':'Motion + tone','settings':{'local_file':str(ROOT/'fixtures'/'motion-tone.mkv'),'looping':True,'restart_on_activate':True},
            'audio':{'tracks':{'1':True,'2':True}},'verification':{'video_signal':True,'audio_signal':True,'sample_seconds':1},
        }]},201)
        pid = profile['id']; path = 'scene-profiles/'+pid
        write('tested-profile.json', profile)
        assert client.get_input_list() == before
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
            job = api(path+'/review','POST',{'seconds':30},202)
            # Mutate saved metadata while review runs; snapshot must stay frozen.
            original_name = profile['name']
            changed = deepcopy(profile); changed['name'] = original_name + ' edited during review'
            api(path,'PUT',changed)
            deadline = time.monotonic()+150
            while job['state'] in ('queued','running') and time.monotonic()<deadline:
                time.sleep(1); job = api('scene-reviews/'+job['job_id'])
            write(label+'.json',job)
            assert job['state']=='completed' and job['result']['status']=='PASS', job
            snapshot = json.loads(Path(job['result']['artifacts']['profile']).read_text(encoding='utf-8'))
            assert snapshot['name']==original_name
            api(path,'PUT',profile)
            passed(label, job['result']['artifacts'])

        review('G4 30s AV tracks 1+2')
        profile['sources'][0]['audio']['tracks']['1']=False
        api(path,'PUT',profile); api(path+'/apply','POST')
        configure_recording(client,2)
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
            client.stop_record()
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
        a,b='PR19 Existing A','PR19 Existing B'
        for target in (a,b):
            if not any(i['inputName']==target for i in client.get_input_list()):
                client.create_input(scene,target,'color_source_v3',{'color':4281554286,'width':640,'height':360})
        existing=api('scene-profiles','POST',{'name':'PR19 Existing binding','sources':[{'type':'existing_video','settings':{'source_name':a}}]},201)
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
        try:
            _restore(client, state)
        except Exception as restore_exc:
            write('restore-failure.json', {
                'session_id': state['session_id'],
                'error': str(restore_exc),
                'at': datetime.now(UTC).isoformat().replace('+00:00','Z'),
            })
            print(f'RESTORE FAILED: {restore_exc}. Session remains active; run restore after fixing OBS.', flush=True)
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['setup','run','restore'])
    action=parser.parse_args().action
    client=ObsClient.from_env()
    try:
        if action=='setup':
            setup(client)
        elif action=='run':
            run(client)
        else:
            state = _read_baseline()
            if not state['active']:
                raise RuntimeError('No active acceptance session to restore.')
            _restore(client, state)
    finally:
        client.close()
