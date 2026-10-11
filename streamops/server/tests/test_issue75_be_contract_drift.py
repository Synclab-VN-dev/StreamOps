"""Contract drift assertions against the real BE in isolated #75 CI only."""
from streamops.server.tests.test_obs_plugin_ws_contract_v2 import _client, _service
from streamops.server.tests.e2e.test_issue75_workflow_matrix import ScenarioWS

def test_fe_mock_schema_matches_be_status_and_catalog(server_config,capture_service):
    fake=ScenarioWS.__new__(ScenarioWS)
    fake.plugin_state="INSTALLED"
    fake.installed_version="1.0"
    fake.release_version="2.0"
    fake.rollback=True
    fake.revision=3
    fake.status_operation={"state":"IDLE","operation_id":None}
    fake.rollback_alias_override=None
    fake.rollback_missing_proof=False
    service,_=_service()
    with _client(server_config,capture_service,service) as api:
        status=api.get("/api/v1/obs/plugins").json()["plugins"][0]
        catalog=api.get("/api/v1/obs/plugins/available").json()["plugins"][0]
        mock_status=fake.status()
        mock_catalog=fake.approved_release()
        assert set(mock_status)<=set(status),set(mock_status)-set(status)
        assert set(mock_catalog)<=set(catalog),set(mock_catalog)-set(catalog)
        assert isinstance(status["rollback"]["available"],bool)
        assert isinstance(mock_status["rollback"]["available"],bool)
        assert isinstance(status["revision"],int)
        assert isinstance(status["operation"],dict)
        assert catalog["release_ref"].startswith("obs-multi-rtmp/v")
        assert mock_catalog["release_ref"].startswith("obs-multi-rtmp/v")
