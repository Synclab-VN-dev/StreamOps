"""Browser E2E for backend-driven recovery notifications after failed operations.

These are mock-WS UI assertions, not evidence that the real BE rollback journal
worked; BE integration and Real-A acceptance remain separate.
"""
from playwright.sync_api import Page, expect
from .conftest import BrowserTestServer
from .test_issue75_workflow_matrix import ScenarioWS, launch, act, confirm


def test_issue75_verify_failure_followed_by_backend_restoration_keeps_failure(
    page: Page, live_server: BrowserTestServer
):
    fake = ScenarioWS(page, plugin_state="UPDATE_AVAILABLE",
                      installed_version="1.0", obs_state="STOPPED")
    launch(page, live_server, fake)
    act(page, "Update plugin")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("2.0")
    fake.operator_starts_obs()
    act(page, "Verify")
    fake.fail_operation = "plugin_verify_failed"
    confirm(page)
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_verify_failed")
    expect(page.locator(".plugin-card")).to_contain_text("Verify failed")

    # A distinct server operation restores the old verified files. Only a
    # backend revision event, never a FE retry, may change the visible state.
    fake.plugin_state = "INSTALLED"
    fake.installed_version = "1.0"
    fake.revision += 1
    fake.push_changed()
    expect(page.locator(".plugin-card")).to_contain_text("Installed")
    expect(page.locator(".plugin-card")).to_contain_text("1.0")
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_verify_failed")
    page.locator(".plugin-activity-details").evaluate("el => el.open=true")
    expect(page.locator("#plugin-activity")).to_contain_text("verify · failed")
    assert [r["operation"] for r in fake.mutations()] == [
        "obs_plugin.update", "obs_plugin.verify"
    ]


def test_issue75_verify_recovery_error_keeps_all_plugin_mutations_disabled(
    page: Page, live_server: BrowserTestServer
):
    fake = ScenarioWS(page, plugin_state="INSTALLED",
                      installed_version="2.0", obs_state="READY", rollback=True)
    launch(page, live_server, fake)
    fake.fail_operation = "plugin_recovery_required"
    act(page, "Verify")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("Recovery required")
    expect(page.get_by_role("button", name="Rollback")).to_be_disabled()
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_recovery_required")
    assert len(fake.mutations("obs_plugin.verify")) == 1
    assert fake.mutations("obs_plugin.rollback") == []


def test_issue75_verify_failed_backend_auto_rollback_failed_recovery(
    page: Page, live_server: BrowserTestServer,
):
    """E2E-10: real BE journal path is verified separately in combined CI.

    A single explicit Verify request returns typed failure while the backend's
    automatic rollback has already failed and moved status to RECOVERY_REQUIRED.
    The browser must never send an additional Rollback/Install or claim success.
    """
    fake = ScenarioWS(page, plugin_state="UPDATE_AVAILABLE",
                      installed_version="1.0", obs_state="STOPPED", rollback=True)
    fake.auto_rollback_failure = True
    launch(page, live_server, fake)
    act(page, "Update plugin")
    confirm(page)
    expect(page.locator(".plugin-card")).to_contain_text("2.0")
    fake.operator_starts_obs()
    fake.fail_operation = "plugin_verify_failed"
    act(page, "Verify")
    confirm(page)
    expect(page.locator("#plugin-notice")).to_contain_text("plugin_verify_failed")
    expect(page.locator(".plugin-card")).to_contain_text("Recovery required")
    expect(page.locator("#plugin-state-scenario-banner")).to_contain_text("Recovery required")
    expect(page.get_by_role("button", name="Rollback")).to_be_disabled()
    assert fake.status_operation["state"] == "FAILED"
    assert fake.status_operation["operation"] == "verify"
    assert fake.plugin_state == "RECOVERY_REQUIRED"
    assert [r["operation"] for r in fake.mutations()] == [
        "obs_plugin.update", "obs_plugin.verify"
    ]
    # Repeated read-only Refresh must not trigger any automatic FE recovery.
    page.locator("#plugin-refresh").click()
    expect(page.locator(".plugin-card")).to_contain_text("Recovery required")
    assert [r["operation"] for r in fake.mutations()] == [
        "obs_plugin.update", "obs_plugin.verify"
    ]
