"""Real interpreter shutdown/pipe regressions; no NVDA, Steam or game launch."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


CHILD = r'''
import os, sqlite3, sys, time, types
from pathlib import Path
import d4planner.daemon as daemon
import d4planner.runtime.storage as storage
# ACL verification is tested separately. This fixture exercises real process/pipe
# lifetime, including shutdown after a constructor failure, in a disposable root.
storage.check_owner = lambda path: None
class Supervisor:
    def __init__(self, **kw):
        if sys.argv[2] == 'constructor-error':
            raise sqlite3.OperationalError('unable to open database file')
        self.stop = kw['stop_event']
        self.status = types.SimpleNamespace(extras={'runtime': {}})
    def run(self):
        print('ready', flush=True)
        if sys.argv[2] == 'owner-death':
            return 0 if self.stop.wait(10) else 99
        # Allow the real watcher to enter its pipe read before interpreter exit.
        time.sleep(.2)
        return int(sys.argv[2])
daemon.Supervisor = Supervisor
raise SystemExit(daemon.main(['--managed-by-hud', '--owner-token', 'test-owner', '--home', sys.argv[1]]))
'''


def spawn_capture(root, case):
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([
        str(Path(__file__).resolve().parents[1] / 'src'),
        *[entry for entry in sys.path if 'site-packages' in entry],
    ])
    for key in ('D4PLANNER_HOME', 'D4PLANNER_DATA_ROOT', 'D4PLANNER_DATA_DIR',
                'D4_RULEKIT_DATA_ROOT', 'D4_LOG_DIR', 'D4_LOG_RUN_ID'):
        env.pop(key, None)
    # Windows venv's redirector is a separate PID. Match the packaged runtime's
    # direct Python process so owner PID assertions cover the actual child.
    executable = getattr(sys, '_base_executable', sys.executable)
    return subprocess.Popen([executable, '-X', 'faulthandler', '-c', CHILD, str(root), case],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)


@pytest.mark.parametrize('case, expected', [('2', 2), ('3', 3), ('constructor-error', 2)])
def test_managed_capture_exits_cleanly_while_owner_pipe_stays_open(tmp_path, case, expected):
    child = spawn_capture(tmp_path / 'capture', case)
    try:
        code = child.wait(timeout=15)  # communicate() would close stdin and hide the bug.
        stderr = child.stderr.read().decode(errors='replace')
        assert code == expected, stderr
        assert 'Fatal Python error' not in stderr
        if case == 'constructor-error':
            state = json.loads((tmp_path / 'capture/state/runtime.json').read_text())
            assert state['state'] == 'BLOCKED'
            assert 'unable to open database file' in state['lastError']
            assert state['supervisorPid'] == child.pid
            assert state['extras']['runtime']['ownerToken'] == 'test-owner'
    finally:
        child.stdin.close()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()


def test_owner_pipe_eof_still_stops_capture(tmp_path):
    child = spawn_capture(tmp_path / 'capture', 'owner-death')
    try:
        child.stdin.close()
        assert child.wait(timeout=15) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()
