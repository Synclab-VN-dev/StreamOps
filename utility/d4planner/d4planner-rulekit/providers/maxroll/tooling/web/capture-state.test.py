import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
import cli
from capture_state import State, atomic, eligible, private_dir


class CaptureStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='capture-state-test-')
        self.root = Path(self.temp.name)
        self.db = State(self.root / 'state')

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_metadata_and_corruption(self):
        def create(i):
            command = {'operation': 'begin', 'run': {'id': str(i)}, 'packages': []}
            subprocess.run(['python3', str(Path(__file__).with_name('capture_state.py')), str(self.db.root)], input=json.dumps(command), text=True, stdout=subprocess.DEVNULL, check=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(create, range(24)))
        self.assertEqual(len(self.db.read()['runs']), 24)
        envelope = json.loads(self.db.file.read_text()); envelope['payload']['revision'] += 1
        self.db.file.write_text(json.dumps(envelope))
        with self.assertRaisesRegex(ValueError, 'CORRUPT'):
            self.db.read()

    def test_activation_recovery_ports_and_invalid_candidate(self):
        configs = json.loads(subprocess.check_output(['node', str(Path(__file__).with_name('activation-fixture.js')), str(self.root / 'snapshots')], text=True))
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
        settings = {'stateRoot': str(self.db.root), 'web': {'port': port}, 'chromium': 'not-used-by-synthetic-probe'}
        directory = private_dir(self.root / 'runtime')
        def register(index):
            c = configs[index]; key = c['snapshotId']; run = 'run-' + key
            package = {'snapshotId': key, 'kind': 'ui', 'mode': 'ui', 'runId': run, 'capturedAt': str(index), 'validationStatus': 'VALIDATED', 'config': c}
            self.db.command({'operation': 'begin', 'run': {'id': run, 'status': 'COMPLETE'}, 'packages': [package]})
        def start(action='start', **kwargs):
            return cli.managed(action, settings, directory, probe=lambda *args: None, **kwargs)
        try:
            register(0)
            first = start(); self.assertEqual(first['snapshotId'], 'fixture-a')
            self.assertEqual(start()['pid'], first['pid'])
            register(1)
            # Real Node process starts, then a post-bind health failure restores old process/selection.
            def fail_new(d, c):
                result = cli.start_owned(d, c)
                if c['snapshotId'] == 'fixture-b':
                    raise RuntimeError('injected post-bind verification failure')
                return result
            with self.assertRaisesRegex(RuntimeError, 'post-bind'):
                start(starter=fail_new)
            self.assertEqual(self.db.read()['activeUi'], 'fixture-a')
            self.assertEqual(cli.diagnostic(cli.runtime_state(directory))['snapshotId'], 'fixture-a')
            self.assertIsNone(self.db.read()['transition'])
            self.db.transact(lambda d: d['packages']['fixture-b'].pop('activationRejected'))
            second = start(); self.assertEqual(second['snapshotId'], 'fixture-b')
            self.assertEqual(self.db.read()['previousActiveUi'], 'fixture-a')
            self.assertEqual(start('rollback')['snapshotId'], 'fixture-a')
            self.assertEqual(start()['snapshotId'], 'fixture-a', 'Rollback cannot immediately reselect rolled-back candidate')
            # Durable journal simulates process death after target is running, before selection commit.
            self.db.command({'operation': 'prepare', 'oldId': 'fixture-a', 'targetId': 'fixture-b', 'action': 'start'})
            cli.stop_owned(directory); cli.start_owned(directory, cli.server_config(self.db.read()['packages']['fixture-b'], port))
            with self.assertRaisesRegex(RuntimeError, 'Interrupted activation'):
                start()
            self.assertEqual(cli.diagnostic(cli.runtime_state(directory))['snapshotId'], 'fixture-a')
            register(2)
            Path(configs[2]['snapshotRoot'], 'fixture-c', 'ui-validation.json').write_text('{}')
            pid = cli.runtime_state(directory)['pid']
            with self.assertRaisesRegex(RuntimeError, 'verify failed'):
                start()
            self.assertEqual(cli.runtime_state(directory)['pid'], pid)
            cli.stop_owned(directory)
            with socket.socket() as occupied:
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                occupied.bind(('127.0.0.1', port)); occupied.listen()
                with self.assertRaises(OSError):
                    start()
                self.assertEqual(occupied.getsockname()[1], port)
        finally:
            cli.stop_owned(directory)

    def test_foreign_process_not_signalled(self):
        child = subprocess.Popen(['sleep', '30'])
        directory = private_dir(self.root / 'runtime')
        try:
            atomic(directory / 'state.json', {'pid': child.pid, 'identity': cli.identity(child.pid), 'config': {}})
            with self.assertRaisesRegex(RuntimeError, 'ownership mismatch'):
                cli.stop_owned(directory)
            self.assertIsNone(child.poll())
        finally:
            child.terminate(); child.wait()

    def test_reused_pid_record_cannot_authorize_orphan_listener(self):
        config = self.root / 'config.json'; config.write_text('{}')
        owner = self.root / 'owner.json'
        child = subprocess.Popen(['node', str(cli.SERVER), '--config', str(config)],
                                 env={**os.environ, 'LOCAL_UI_OWNER_STATE': str(owner)},
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            atomic(owner, {'pid': child.pid, 'identity': '0'})
            stdout, stderr = child.communicate(timeout=10)
            self.assertNotEqual(child.returncode, 0)
            self.assertIn('ownership was not committed', stderr)
            self.assertNotIn('"ready":true', stdout)
        finally:
            if child.poll() is None: child.terminate(); child.wait()


if __name__ == '__main__':
    os.umask(0o077)
    unittest.main()
