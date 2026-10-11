"""Regression for startup-only GitHub token and secret-free Plugin Manager diagnostics."""

from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

from streamops.server.errors import ObsPluginError
from streamops.server.services.obs_plugin_release_source import (
    GitHubReleaseSource,
    configured_plugin_release_source,
)


def test_missing_token_does_not_send_anonymous_github_api_request(monkeypatch):
    monkeypatch.setenv("STREAMOPS_OBS_PLUGIN_SOURCE_PROVIDER", "github-release")
    monkeypatch.setenv(
        "STREAMOPS_OBS_PLUGIN_SOURCE_LOCATION", "Synclab-VN-dev/StreamOps-OBS-Plugins"
    )
    monkeypatch.setenv(
        "STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN_ENV", "STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN"
    )
    monkeypatch.delenv("STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN", raising=False)
    managed = configured_plugin_release_source()
    with pytest.raises(ObsPluginError) as failure:
        managed.catalog_release("obs-multi-rtmp")
    assert failure.value.code == "plugin_github_token_missing"
    assert failure.value.status_code == 503
    assert "token" in str(failure.value).lower()


def test_provided_token_goes_only_to_approved_github_transport():
    marker = "secret-must-not-be-logged"
    captured = []

    def fake_transport(url, *, accept, token, max_bytes):
        captured.append((url, accept, token))
        return b"[]"

    src = GitHubReleaseSource(
        "Synclab-VN-dev/StreamOps-OBS-Plugins",
        token=marker, transport=fake_transport, require_token=True,
    )
    with pytest.raises(ObsPluginError) as failure:
        src.latest("obs-multi-rtmp")
    assert failure.value.code == "plugin_release_unavailable"
    assert marker not in str(failure.value)
    assert len(captured) == 1
    assert captured[0][0].startswith(
        "https://api.github.com/repos/Synclab-VN-dev/StreamOps-OBS-Plugins/"
    )
    assert captured[0][2] == marker


@pytest.mark.parametrize(
    ("status", "remaining", "code"),
    [
        (403, "0", "plugin_github_rate_limited"),
        (403, "20", "plugin_github_auth_failed"),
        (401, None, "plugin_github_auth_failed"),
        (500, None, "plugin_release_source_error"),
    ],
)
def test_github_http_errors_are_typed_and_never_expose_token(status, remaining, code):
    headers = Message()
    if remaining is not None:
        headers["X-RateLimit-Remaining"] = remaining
    marker = "secret-must-not-be-logged"

    def fake_transport(url, *, accept, token, max_bytes):
        assert token == marker
        raise HTTPError(url, status, f"raw error {marker}", headers, None)

    src = GitHubReleaseSource(
        "Synclab-VN-dev/StreamOps-OBS-Plugins",
        token=marker, transport=fake_transport, require_token=True,
    )
    with pytest.raises(ObsPluginError) as failure:
        src.latest("obs-multi-rtmp")
    assert failure.value.code == code
    assert failure.value.status_code == 503
    assert marker not in str(failure.value)


def test_windows_launcher_has_no_plaintext_token_cli_contract():
    root = Path(__file__).resolve().parents[3]
    start = (root / "scripts/devices/a-windows/start-streamops-node.ps1").read_text(
        encoding="utf-8"
    )
    runner = (root / "scripts/devices/a-windows/run-streamops-node.ps1").read_text(
        encoding="utf-8"
    )
    assert "Read-Host" in start and "-AsSecureString" in start
    assert "ConvertFrom-SecureString" in start
    assert "protect-obs-plugin-token-dir.ps1" in start
    assert "Set-Acl -LiteralPath $secretDir" not in start
    assert "ObsPluginCredentialFile" in runner
    assert "ConvertTo-SecureString" in runner
    assert "ZeroFreeBSTR" in runner
    assert "Remove-Item -LiteralPath $ObsPluginCredentialFile" in runner
    assert "STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN_ENV" in runner


def test_powershell_launchers_parse_on_windows():
    import shutil
    import subprocess
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows PowerShell parse gate")
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        pytest.fail("Windows CI has no PowerShell available to parse launcher")
    root = Path(__file__).resolve().parents[3]
    for name in (
        "start-streamops-node.ps1",
        "run-streamops-node.ps1",
        "protect-obs-plugin-token-dir.ps1",
    ):
        path = root / "scripts/devices/a-windows" / name
        quoted_path = str(path).replace("'", "''")
        command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{quoted_path}',[ref]$tokens,[ref]$errors) | Out-Null; "
            "if($errors.Count -gt 0){ $errors | Format-List; exit 1 }"
        )
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, f"{name} parse failed: {result.stderr} {result.stdout}"


def test_powershell_token_directory_acl_without_admin():
    """Actual Windows DACL smoke: protect a fresh user-owned folder and verify
    only the current user has explicit access; do not just parse the script.
    """
    import shutil
    import subprocess
    import sys
    import tempfile

    if sys.platform != "win32":
        pytest.skip("Windows DACL smoke gate")
    executable = shutil.which("pwsh") or shutil.which("powershell")
    assert executable, "Windows CI requires PowerShell"
    root = Path(__file__).resolve().parents[3]
    helper = root / "scripts/devices/a-windows/protect-obs-plugin-token-dir.ps1"
    with tempfile.TemporaryDirectory() as tmpdir:
        secret_dir = Path(tmpdir) / ".secrets"
        secret_dir.mkdir()
        # Simulate the real Windows case where an explicit non-user ACE
        # survives /inheritance:r (not merely an inherited permission).
        preseed = subprocess.run(
            ["icacls.exe", str(secret_dir), "/grant",
             "*S-1-5-32-545:(OI)(CI)R"],
            capture_output=True, text=True, timeout=20,
        )
        assert preseed.returncode == 0, preseed.stderr + preseed.stdout
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-File",
             str(helper), "-Directory", str(secret_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            "DACL restriction failed for a normal owned folder: "
            + result.stderr + result.stdout
        )
        acl = subprocess.run(
            ["icacls.exe", str(secret_dir)],
            capture_output=True, text=True, timeout=20,
        )
        assert acl.returncode == 0
        # Helper validates SID-based, owner-only DACL and removed inheritance.
        assert secret_dir.is_dir()
        canary = secret_dir / "handoff.canary"
        canary.write_text("not a real token", encoding="utf-8")
        assert canary.read_text(encoding="utf-8") == "not a real token"
