"""Renderer cleanup owns the npm process tree; it must not kill unrelated Node processes."""
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from .e2e import test_magicpath_visual as visual


def test_windows_renderer_tree_stops_before_wait():
    process=Mock(pid=1234);process.poll.return_value=None
    with patch.object(visual.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
        visual._stop_reference_renderer(process,windows=True)
    assert run.call_args.args[0]==['taskkill','/PID','1234','/T','/F']
    process.wait.assert_called_once_with(timeout=10)
    process.terminate.assert_not_called()


def test_exited_renderer_does_not_kill_a_reused_pid():
    process=Mock(pid=1234);process.poll.return_value=0
    with patch.object(visual.subprocess,'run') as run:
        visual._stop_reference_renderer(process,windows=True)
    run.assert_not_called()


def test_windows_cleanup_failure_does_not_claim_success():
    process=Mock(pid=1234);process.poll.return_value=None
    with patch.object(visual.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
        with pytest.raises(RuntimeError,match='renderer process tree'):
            visual._stop_reference_renderer(process,windows=True)
