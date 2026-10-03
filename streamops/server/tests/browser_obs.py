"""Only the OBS transport is fake; tests use real service/store/media gates."""
from copy import deepcopy
from io import BytesIO
import shutil
import subprocess
import time
from PIL import Image
from streamops.server.errors import ObsWebSocketConnectionError
from streamops.server.tests.test_obs_scene import AudioFakeObsClient


class BrowserObs(AudioFakeObsClient):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.offline = False
        self.recording_output_path = root / 'recording.mkv'
        self.stream_service = {
            'streamServiceType': 'rtmp_common',
            'streamServiceSettings': {'service': 'Existing', 'key': 'browser-private-restore-key'},
        }
        self.stream_started_at = None

    def get_version(self):
        if self.offline:
            raise ObsWebSocketConnectionError('Test OBS unavailable')
        return super().get_version()

    def get_source_screenshot(self, *args, **kwargs):
        output = BytesIO()
        Image.new('RGB', (160, 90), '#2da486').save(output, format='PNG')
        return output.getvalue()

    def get_profile_parameter(self, category, name):
        return {('Output', 'Mode'): 'Advanced', ('AdvOut', 'RecType'): 'Standard', ('AdvOut', 'RecTracks'): '2'}[(category, name)]

    def get_stream_service_settings(self):
        return deepcopy(self.stream_service)

    def set_stream_service_settings(self, service_type, settings):
        self.stream_service = {
            'streamServiceType': service_type,
            'streamServiceSettings': deepcopy(settings),
        }

    def start_stream(self):
        self.streaming = True
        self.stream_started_at = time.monotonic()

    def stop_stream(self):
        self.streaming = False
        self.stream_started_at = None

    def get_stream_status(self):
        duration_ms = 0
        if self.streaming and self.stream_started_at is not None:
            duration_ms = max(1000, int((time.monotonic() - self.stream_started_at) * 1000))
        return {
            'outputActive': self.streaming,
            'outputReconnecting': False,
            'outputDuration': duration_ms,
            'outputBytes': int(duration_ms * 25) if self.streaming else 0,
            'outputCongestion': 0.01 if self.streaming else 0.0,
            'outputSkippedFrames': 0,
            'outputTotalFrames': int(duration_ms * 0.06) if self.streaming else 0,
        }

    def get_stats(self):
        return {'activeFps': 60.0 if self.streaming else 0.0, 'cpuUsage': 5.0}

    def stop_record(self):
        self.recording = False
        video = self.video_settings
        subprocess.run([shutil.which('ffmpeg'), '-y', '-v', 'error', '-f', 'lavfi', '-i',
                        f"color=c=green:s={video['outputWidth']}x{video['outputHeight']}:r=60",
                        '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-c:a', 'aac', str(self.recording_output_path)], check=True, capture_output=True)
        return {'outputPath': str(self.recording_output_path)}
