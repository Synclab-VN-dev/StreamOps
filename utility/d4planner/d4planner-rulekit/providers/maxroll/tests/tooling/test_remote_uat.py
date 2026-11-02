import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'tooling' / 'remote-uat.py'
spec = importlib.util.spec_from_file_location('remote_uat', SCRIPT)
uat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uat)


class OwnershipTests(unittest.TestCase):
    def test_reused_or_stale_pid_is_not_owned(self):
        self.assertFalse(uat.alive({'pid': os.getpid(), 'startTime': 'wrong'}))
        self.assertTrue(uat.alive({'pid': os.getpid(), 'startTime': uat.identity(os.getpid())}))

    def test_occupied_port_is_rejected_without_disruption(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); sock.listen()
            port = sock.getsockname()[1]
            with self.assertRaises(OSError):
                uat.free_port(port)
            self.assertTrue(uat.listening(port))

    def test_dead_child_fails_readiness(self):
        child = subprocess.Popen(['true']); child.wait()
        with self.assertRaisesRegex(RuntimeError, 'Owned child exited'):
            uat.wait_for(lambda: True, [child], timeout=1)

    def test_stop_does_not_signal_unrelated_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            uat.write_json(runtime / 'state.json', {'pid': os.getpid(), 'startTime': 'wrong'})
            result = subprocess.run(['python3', str(SCRIPT), 'stop', '--runtime', directory],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['pid'], os.getpid())

    def test_config_failure_does_not_start_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            config = runtime / 'config.json'
            config.write_text(json.dumps({'vncPort': 80}))
            with self.assertRaisesRegex(ValueError, 'Invalid display'):
                uat.supervise(config, runtime)
            self.assertFalse((runtime / 'state.json').exists())


if __name__ == '__main__':
    unittest.main()
