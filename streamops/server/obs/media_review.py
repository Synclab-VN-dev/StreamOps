"""Profile-aware recorded media gates; no implicit Track 1 policy."""
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from ..errors import SceneOperationError
from .scene import Check


def recording_tracks(client):
    """OBS standard recording packs enabled tracks in ascending track order."""
    mode = client.get_profile_parameter('Output', 'Mode')
    if mode == 'Simple':
        return [1]
    if mode != 'Advanced' or client.get_profile_parameter('AdvOut', 'RecType') != 'Standard':
        raise SceneOperationError('Review requires Simple or Advanced/Standard recording with known track mapping.')
    try:
        mask = int(client.get_profile_parameter('AdvOut', 'RecTracks'))
    except (ValueError, TypeError) as exc:
        raise SceneOperationError('Could not read OBS recording track mask.') from exc
    return [i for i in range(1, 7) if mask & (1 << (i-1))]


def expected_audio(profile):
    expected, thresholds = set(), {}
    for source in profile['sources']:
        audio = source.get('audio')
        if not source['enabled'] or not audio or not audio.get('enabled', True) or audio['muted']:
            continue
        for track, enabled in audio['tracks'].items():
            if enabled:
                track = int(track)
                expected.add(track)
                if source['verification']['audio_signal']:
                    thresholds[track] = min(thresholds.get(track, 0), source['verification']['audio_threshold_db'])
    return expected, thresholds


def analyze_recording(path: Path, probe, profile, selected_tracks, seconds):
    checks = []
    def check(key, passed, expected, actual):
        checks.append(Check('review.'+key, 'PASS' if passed else 'FAIL', key.replace('_',' '), expected, actual))
    videos = [s for s in probe.get('streams',[]) if s.get('codec_type') == 'video']
    audios = [s for s in probe.get('streams',[]) if s.get('codec_type') == 'audio']
    check('video_stream', bool(videos), True, bool(videos))
    duration = float((probe.get('format') or {}).get('duration') or 0)
    check('duration', math.isfinite(duration) and max(0.1, seconds-2) <= duration <= seconds+5, {'seconds':seconds,'tolerance':[-2,5]}, duration)
    if videos:
        video = videos[0]
        canvas = profile['canvas']
        check('resolution', (video.get('width'),video.get('height')) == (canvas['width'],canvas['height']), [canvas['width'],canvas['height']], [video.get('width'),video.get('height')])
        try: fps = float(Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate') or '0'))
        except (ValueError, ZeroDivisionError): fps = 0
        check('fps', abs(fps-canvas['fps']) <= canvas['fps']*.01, canvas['fps'], fps)
    expected, thresholds = expected_audio(profile)
    mapping_valid = len(audios) == len(selected_tracks)
    check('audio_mapping', not expected or mapping_valid, selected_tracks if expected else 'Audio optional', len(audios))
    for track in sorted(expected):
        present = track in selected_tracks and mapping_valid
        check(f'audio_track_{track}', present, True, present)
    peaks = {}
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SceneOperationError('ffmpeg is required to decode and analyze the review recording.')
    decoded = subprocess.run([ffmpeg,'-v','error','-xerror','-i',str(path),'-map','0:v:0','-f','null','-'], capture_output=True, text=True, timeout=max(30, seconds*2))
    check('decode', decoded.returncode == 0, 'decodable video', decoded.stderr[-1500:])
    for track, threshold in thresholds.items():
        if track not in selected_tracks or not mapping_valid:
            continue
        index = selected_tracks.index(track)
        analysis = subprocess.run([ffmpeg,'-hide_banner','-i',str(path),'-map',f'0:a:{index}','-af','volumedetect','-f','null','-'], capture_output=True, text=True, timeout=max(30,seconds*2))
        match = re.search(r'max_volume:\s*(-?\d+(?:\.\d+)?|-?inf) dB', analysis.stderr)
        peak = float(match.group(1)) if match else None
        peaks[str(track)] = peak if peak is not None and math.isfinite(peak) else None
        check(f'audio_track_{track}_signal', analysis.returncode == 0 and peak is not None and peak >= threshold, {'peak_db_at_least':threshold}, peaks[str(track)])
    return checks, {'probe':probe,'selected_tracks':selected_tracks,'expected_audio_tracks':sorted(expected),'peak_db':peaks}
