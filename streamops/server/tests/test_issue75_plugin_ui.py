"""Independent FE route and asset smoke; actual plugin mutations require Real-A approval."""
from fastapi.testclient import TestClient

from streamops.server.app import create_app


def test_issue75_page_and_browser_assets(server_config, capture_service):
    app = create_app(server_config, capture_service=capture_service, manage_runtime=False)
    with TestClient(app) as client:
        page = client.get("/obs/plugins")
        assert page.status_code == 200
        assert "OBS Plugin Manager" in page.text
        assert 'id="plugin-managed-count"' in page.text
        assert 'id="plugin-confirm-dialog"' in page.text
        assert 'id="plugin-activity"' in page.text
        assert page.headers.get("cache-control") == "no-store"
        for asset in (
            "obs-plugins/core.mjs", "obs-plugins/transport.mjs",
            "obs-plugins/page.mjs", "obs-plugins/dashboard.mjs",
            "obs-plugins/plugin-manager.css",
        ):
            response = client.get("/assets/" + asset)
            assert response.status_code == 200, asset
            assert response.content


def test_issue75_dashboard_links_to_plugin_manager(server_config, capture_service):
    app = create_app(server_config, capture_service=capture_service, manage_runtime=False)
    with TestClient(app) as client:
        response = client.get("/obs")
    assert response.status_code == 200
    assert 'href="/obs/plugins"' in response.text
    assert 'id="plugin-dashboard-managed"' in response.text
