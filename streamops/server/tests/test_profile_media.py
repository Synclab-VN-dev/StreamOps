from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import pytest

from streamops.server.obs.media_review import analyze_recording, recording_tracks
from streamops.server.scene_profiles import normalize_profile


def profile(audio=True):
    return normalize_profile({'name':'Media gate','sources':[{'type':'browser_source',
        'settings':{'url':'https://example.invalid'}, 'audio':{'tracks':{'2':True}} if audio else None,
        'verification':{'audio_signal':audio}}]})


@pytest.fixture
def media(monkeypatch):
    from streamops.server.obs import media_review
    monkeypatch.setattr(media_review.shutil, 'which', lambda _: 'ffmpeg')
    state={'peak':-15, 'decode':0}
    def run(args, **kwargs):
        return SimpleNamespace(returncode=state['decode'] if '-xerror' in args else 0,
                               stderr=f"max_volume: {state['peak']} dB")
    monkeypatch.setattr(media_review.subprocess, 'run', run)
    return state


def probe(audio=True):
    return {'format':{'duration':'30'},'streams':[{'codec_type':'video','width':1920,'height':1080,'avg_frame_rate':'60000/1000'}]+([{'codec_type':'audio'}] if audio else [])}


def failures(checks):
    return [c.id for c in checks if c.status=='FAIL']


def test_recording_video_only_and_track_two(media):
    checks,_=analyze_recording(Path('sample'),probe(False),profile(False),[2],30)
    assert not failures(checks)
    checks,analysis=analyze_recording(Path('sample'),probe(),profile(),[2],30)
    assert not failures(checks)
    assert analysis['peak_db']=={'2':-15}


@pytest.mark.parametrize('case', ['missing_audio','wrong_track','silent','wrong_fps','wrong_size','short','decode_error','no_video'])
def test_recording_negative_matrix(media,case):
    data=probe(); tracks=[2]
    if case=='missing_audio': data['streams']=data['streams'][:1]
    if case=='wrong_track': tracks=[1]
    if case=='silent': media['peak']=-91
    if case=='wrong_fps': data['streams'][0]['avg_frame_rate']='30/1'
    if case=='wrong_size': data['streams'][0]['width']=1280
    if case=='short': data['format']['duration']='2'
    if case=='decode_error': media['decode']=1
    if case=='no_video': data['streams']=data['streams'][1:]
    checks,_=analyze_recording(Path('sample'),data,profile(),tracks,30)
    assert failures(checks)


def test_sparse_obs_recording_track_mapping():
    class Client:
        def get_profile_parameter(self,c,n):
            return {'Mode':'Advanced','RecType':'Standard','RecTracks':'34'}[n]
    assert recording_tracks(Client())==[2,6]


def test_missing_required_recording_track_explains_global_obs_mismatch(media):
    checks,_ = analyze_recording(Path('sample'), probe(), profile(), [1], 30)
    track = next(check for check in checks if check.id == 'review.audio_track_2')

    assert track.status == 'FAIL'
    assert track.message == (
        'Recording audio track 2 is required by the profile, '
        'but OBS recording output does not include track 2.'
    )
    assert track.expected == 'Track 2 enabled'
    assert track.actual == [1]
