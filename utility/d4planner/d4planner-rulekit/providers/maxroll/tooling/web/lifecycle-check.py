#!/usr/bin/env python3
"""Opt-in real snapshot CLI lifecycle and startup failure integration check."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

cli = Path(__file__).with_name('cli.py')
config = json.loads(Path(os.environ['LOCAL_EDITOR_CONFIG']).read_text())
with tempfile.TemporaryDirectory(prefix='snapshot-web-test-') as directory:
    config_path = Path(directory) / 'config.json'
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    config['port'] = port
    config_path.write_text(json.dumps(config))
    def run(action, success=True):
        result = subprocess.run([sys.executable, str(cli), action, '--config', str(config_path)], capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result.stdout
    try:
        for _ in range(3):
            started = json.loads(run('start').splitlines()[0])
            assert started['status'] == 'READY'
            assert json.loads(run('start').splitlines()[0])['pid'] == started['pid']
            assert json.loads(run('status').splitlines()[0])['pid'] == started['pid']
            config_path.write_text(json.dumps({**config, 'manifestSha256': '0' * 64}))
            run('start', success=False)
            config_path.write_text(json.dumps(config))
            assert run('stop').startswith('STOPPED')
            assert run('status').strip() == 'STOPPED'
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1', port))
        with socket.socket() as occupied:
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            occupied.bind(('127.0.0.1', port)); occupied.listen()
            run('start', success=False)
            assert occupied.getsockname()[1] == port
        config['manifestSha256'] = '0' * 64
        config_path.write_text(json.dumps(config))
        run('start', success=False)
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
        print('PASS: 3 start/reuse/status/stop cycles; port conflict preserved; snapshot mismatch fail-closed; ports released')
    finally:
        run('stop')
