from __future__ import annotations

from pathlib import Path

from streamops.server.obs.scene import apply_scene, verify_scene
from streamops.tests.fake_obs import FakeObsClient


class AudioFakeObsClient(FakeObsClient):
    def __init__(self) -> None:
        super().__init__()
        self.input_kinds = ["browser_source", "monitor_capture"]
        self.audio_muted: dict[str, bool] = {}
        self.audio_volume_db: dict[str, float] = {}
        self.audio_sync_ms: dict[str, int] = {}
        self.audio_tracks: dict[str, dict[str, bool]] = {}
        self.audio_peaks: dict[str, float | None] = {}

    def create_input(
        self,
        scene_name: str,
        input_name: str,
        input_kind: str,
        input_settings: dict,
        *,
        enabled: bool = True,
    ) -> int:
        scene_item_id = super().create_input(
            scene_name,
            input_name,
            input_kind,
            input_settings,
            enabled=enabled,
        )
        self.audio_muted.setdefault(input_name, False)
        self.audio_volume_db.setdefault(input_name, 0.0)
        self.audio_sync_ms.setdefault(input_name, 0)
        self.audio_tracks.setdefault(
            input_name,
            {str(index): index == 1 for index in range(1, 7)},
        )
        return scene_item_id

    def get_input_mute(self, input_name: str) -> bool:
        return self.audio_muted[input_name]

    def set_input_mute(self, input_name: str, muted: bool) -> None:
        self.audio_muted[input_name] = muted

    def get_input_volume(self, input_name: str) -> dict:
        return {"inputVolumeDb": self.audio_volume_db[input_name]}

    def set_input_volume_db(self, input_name: str, volume_db: float) -> None:
        self.audio_volume_db[input_name] = volume_db

    def get_input_audio_sync_offset(self, input_name: str) -> int:
        return self.audio_sync_ms[input_name]

    def set_input_audio_sync_offset(self, input_name: str, offset_ms: int) -> None:
        self.audio_sync_ms[input_name] = offset_ms

    def get_input_audio_tracks(self, input_name: str) -> dict[str, bool]:
        return dict(self.audio_tracks[input_name])

    def set_input_audio_tracks(self, input_name: str, tracks: dict[str, bool]) -> None:
        self.audio_tracks[input_name] = dict(tracks)

    def sample_input_volume_meters(
        self,
        input_names: list[str],
        *,
        seconds: float,
    ) -> dict[str, dict]:
        return {
            name: {
                "sample_count": 10,
                "peak_db": self.audio_peaks.get(name, -12.0),
                "mean_db": self.audio_peaks.get(name, -18.0),
            }
            for name in input_names
        }


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "livestream-test.yaml"
    path.write_text(
        """
name: livestream-test
video:
  base_width: 1920
  base_height: 1080
  output_width: 1920
  output_height: 1080
  fps: 60
sources:
  game:
    source_name: Test Game
    role: main
    media: video
    layer: 0
    managed: true
    input_kind: browser_source
    settings:
      width: 1920
      height: 1080
  camera:
    source_name: Test Camera
    role: camera
    media: video
    layer: 1
    anchor: bottom_right
    width_percent: 22
    margin_right: 40
    margin_bottom: 40
    managed: true
    input_kind: browser_source
    settings:
      width: 640
      height: 360
  game_audio:
    source_name: Test Game Audio
    role: game_audio
    media: audio
    layer: 2
    managed: true
    input_kind: browser_source
    audio:
      tracks:
        "1": true
        "2": true
      signal_required: true
      signal_threshold_db: -60
  voice:
    source_name: Test Voice
    role: voice
    media: audio
    layer: 3
    managed: true
    input_kind: browser_source
    audio:
      tracks:
        "1": true
        "3": true
      signal_required: true
      signal_threshold_db: -60
""".strip(),
        encoding="utf-8",
    )
    return path


def test_apply_reconciles_audio_and_is_idempotent(tmp_path: Path) -> None:
    obs = AudioFakeObsClient()
    config_path = _config(tmp_path)

    first = apply_scene(
        "livestream-test",
        client=obs,
        root=tmp_path,
        config_path=config_path,
    )
    second = apply_scene(
        "livestream-test",
        client=obs,
        root=tmp_path,
        config_path=config_path,
    )

    assert first.changed is True
    assert second.changed is False
    assert obs.audio_tracks["Test Game Audio"]["2"] is True
    assert obs.audio_tracks["Test Voice"]["3"] is True
    assert obs.audio_tracks["Test Voice"]["2"] is False


def test_verify_runtime_audio_requires_real_signal(tmp_path: Path) -> None:
    obs = AudioFakeObsClient()
    config_path = _config(tmp_path)
    apply_scene("livestream-test", client=obs, root=tmp_path, config_path=config_path)

    passing = verify_scene(
        "livestream-test",
        client=obs,
        root=tmp_path,
        config_path=config_path,
        runtime_audio=True,
    )

    obs.audio_peaks["Test Voice"] = -90.0
    failing = verify_scene(
        "livestream-test",
        client=obs,
        root=tmp_path,
        config_path=config_path,
        runtime_audio=True,
    )

    assert passing.status == "PASS"
    assert failing.status == "FAIL"
    assert any(
        check.id == "audio.voice.signal"
        and check.status == "FAIL"
        for check in failing.checks
    )


def test_apply_repairs_audio_drift(tmp_path: Path) -> None:
    obs = AudioFakeObsClient()
    config_path = _config(tmp_path)
    apply_scene("livestream-test", client=obs, root=tmp_path, config_path=config_path)
    obs.audio_muted["Test Voice"] = True
    obs.audio_tracks["Test Game Audio"]["2"] = False

    before = verify_scene(
        "livestream-test",
        client=obs,
        root=tmp_path,
        config_path=config_path,
    )
    repaired = apply_scene(
        "livestream-test",
        client=obs,
        root=tmp_path,
        config_path=config_path,
    )
    after = verify_scene(
        "livestream-test",
        client=obs,
        root=tmp_path,
        config_path=config_path,
    )

    assert before.status == "FAIL"
    assert repaired.changed is True
    assert after.status == "PASS"
