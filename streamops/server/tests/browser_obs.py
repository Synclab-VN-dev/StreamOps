"""Only the OBS transport is fake; tests use real service/store/media gates."""
from io import BytesIO
import shutil
import subprocess
from PIL import Image
from streamops.server.errors import ObsWebSocketConnectionError
from streamops.server.tests.test_obs_scene import AudioFakeObsClient


class BrowserObs(AudioFakeObsClient):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.offline = False
        self.recording_output_path = root / 'recording.mkv'

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

    def stop_record(self):
        self.recording = False
        video = self.video_settings
        subprocess.run([shutil.which('ffmpeg'), '-y', '-v', 'error', '-f', 'lavfi', '-i',
                        f"color=c=green:s={video['outputWidth']}x{video['outputHeight']}:r=60",
                        '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-c:a', 'aac', str(self.recording_output_path)], check=True, capture_output=True)
        return {'outputPath': str(self.recording_output_path)}
