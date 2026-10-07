from pathlib import Path

WEB = Path(__file__).parents[1] / "web"

def test_stream_manager_v2_uses_public_multistream_contract_only():
    js = (WEB / "stream-manager-v2.js").read_text(encoding="utf-8")
    assert "/api/v1/multistream" in js
    assert "/api/v1/multistream/ws" in js
    for forbidden in ("CallVendorRequest", "plugin_target_id", "sorayuki.multi_rtmp"):
        assert forbidden not in js

def test_stream_manager_v2_covers_all_runtime_states_and_no_optimistic_live():
    js = (WEB / "stream-manager-v2.js").read_text(encoding="utf-8")
    for state in ("IDLE", "STARTING", "LIVE", "RECONNECTING", "STOPPING", "FAILED"):
        assert state in js
    assert "start accepted →" not in js or "state(result)" in js
    assert "stop accepted →" not in js or "state(result)" in js

def test_stream_manager_v2_never_renders_credential_value():
    js = (WEB / "stream-manager-v2.js").read_text(encoding="utf-8")
    html = (WEB / "stream.html").read_text(encoding="utf-8")
    assert 'type="password"' in html
    assert "Stored credential is never displayed" in js
    assert "$('#destination-credential').value = '';" in js
    assert "<strong>Configured</strong>" in js

def test_stream_manager_v2_has_required_hierarchy():
    html = (WEB / "stream.html").read_text(encoding="utf-8")
    for text in ("OBS session", "Preflight", "Destinations", "Stream Activity", "+ Add destination"):
        assert text in html


def test_stream_manager_v2_uses_backend_shared_preflight():
    js = (WEB / "stream-manager-v2.js").read_text(encoding="utf-8")
    service = (Path(__file__).parents[1] / "services" / "live.py").read_text(encoding="utf-8")
    api = (Path(__file__).parents[1] / "api" / "live.py").read_text(encoding="utf-8")
    ws = (Path(__file__).parents[1] / "services" / "live_ws_operations.py").read_text(encoding="utf-8")
    assert "/api/v1/live/preflight/shared" in js
    assert "preflight?.status === 'PASS'" in js
    assert "def shared_preflight(self, profile_id: str)" in service
    assert '@router.post("/live/preflight/shared")' in api
    assert '"live.preflight.shared": self._live_preflight_shared' in ws
    assert "self.service.shared_preflight(profile_id)" in ws


def test_legacy_preflight_composes_shared_core():
    service = (Path(__file__).parents[1] / "services" / "live.py").read_text(encoding="utf-8")
    assert 'shared = self.shared_preflight(profile_id)' in service
    assert '"destination_id": destination_id' in service
