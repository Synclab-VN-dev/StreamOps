from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv

import pytest


@pytest.mark.skipif(not os.environ.get("STREAMOPS_TEST_WHEEL"), reason="CI wheel acceptance supplies the built wheel")
def test_installed_wheel_runs_outside_source_checkout():
    wheel = Path(os.environ["STREAMOPS_TEST_WHEEL"]).resolve()
    assert wheel.is_file()
    with tempfile.TemporaryDirectory(prefix="streamops-wheel-acceptance-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        workdir = root / "work"
        data_dir = root / "state"
        workdir.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", f"{wheel}[server]"], check=True, capture_output=True, text=True)
        probe = subprocess.run(
            [str(python), "-c", "import importlib.resources, streamops.server.platform.windows.obs_plugin as p; print(p.__file__); print(importlib.resources.files(p).joinpath('manifest.json').is_file()); print(importlib.resources.files('streamops.server').joinpath('data/games.seed.json').is_file())"],
            cwd=workdir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        assert str(root).casefold() in probe[0].casefold()
        assert probe[1] == "True"
        assert probe[2] == "True"  # packaged game seed in installed wheel

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        if os.name == "nt":
            command = [
                str(environment / "Scripts/streamops-node.exe"), "--host", "127.0.0.1",
                "--port", str(port), "--data-dir", str(data_dir), "--capture-timeout", "0.2",
            ]
        else:
            smoke_server = (
                "from types import SimpleNamespace\n"
                "from pathlib import Path\n"
                "import uvicorn\n"
                "from streamops.server.config import ServerConfig\n"
                "from streamops.server.app import create_app\n"
                "from streamops.server.api import health\n"
                "from streamops.server.obs.manager import ObsRuntimeStatus\n"
                "health.desktop_session_info = lambda: SimpleNamespace(current_session_id=0, active_console_session_id=0)\n"
                "class Capture:\n"
                "    ready=True\n    backend_name='wheel-smoke'\n"
                "    def start(self): pass\n    def close(self): pass\n"
                "class Manager:\n"
                "    def status(self): return ObsRuntimeStatus('STOPPED', {'running': False}, {'connected': False, 'obs_version': None}, {'streaming': False, 'recording': False}, None)\n"
                f"app=create_app(ServerConfig('127.0.0.1',{port},0,Path({str(data_dir)!r}),0.2,'warning'), capture_service=Capture(), obs_manager=Manager(), manage_runtime=False)\n"
                f"uvicorn.run(app,host='127.0.0.1',port={port},log_level='warning')\n"
            )
            command = [str(python), "-c", smoke_server]
        child_env = os.environ.copy()
        for key in list(child_env):
            if key.upper().startswith(("OBS_WEBSOCKET", "STREAMOPS_SECRET", "RTMP", "STREAM_KEY")):
                child_env.pop(key, None)
        output = (root / "server.log").open("wb")
        process = subprocess.Popen(command, cwd=workdir, env=child_env, stdout=output, stderr=subprocess.STDOUT)
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError("Installed StreamOps process exited before health became available.")
                try:
                    with urllib.request.urlopen(base + "/api/v1/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.25)
            else:
                raise AssertionError("Installed StreamOps did not become healthy outside the checkout.")
            with urllib.request.urlopen(base + "/api/v1/obs/plugins/obs-multi-rtmp", timeout=10) as response:
                payload = json.loads(response.read())
            assert payload["plugin_id"] == "obs-multi-rtmp"
            assert payload["expected_version"] == "0.7.4.0"
            assert set(payload) == {"plugin_id", "expected_version", "state", "installed", "loaded", "compatible"}
            # G6: GameService is discoverable from the installed wheel,
            # not an editable repository checkout.
            with urllib.request.urlopen(base + "/api/v1/games", timeout=10) as response:
                games = json.loads(response.read())
            assert games["total"] == 1
            assert games["games"][0]["id"] == "steam:2344520"
            ws_probe = (
                "import json,sys\\n"
                "from websockets.sync.client import connect\\n"
                "port=sys.argv[1]\\n"
                "with connect('ws://127.0.0.1:'+port+'/api/v1/games/ws',open_timeout=8) as ws:\\n"
                "    snapshot=json.loads(ws.recv(timeout=8))\\n"
                "    assert snapshot['event']=='games.snapshot'\\n"
                "    assert snapshot['data']['games'][0]['id']=='steam:2344520'\\n"
                "    ws.send(json.dumps({'type':'request','request_id':'wheel','operation':'games.list','payload':{}}))\\n"
                "    for _ in range(12):\\n"
                "        message=json.loads(ws.recv(timeout=8))\\n"
                "        if message.get('request_id')=='wheel':\\n"
                "            assert message['ok'] and message['data']['total']==1\\n"
                "            break\\n"
                "    else: raise AssertionError('no WS response from installed wheel')\\n"
            )
            # Test the WS server as a separate process using the installed
            # wheel's venv, never site-packages from this CI checkout.
            subprocess.run([str(python), "-c", ws_probe, str(port)], cwd=workdir,
                           check=True, timeout=30, capture_output=True, text=True)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            output.close()
