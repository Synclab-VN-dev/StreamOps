"""UNIT-04/G5: PID/session/image ambiguity must fail closed."""
from pathlib import Path
from types import SimpleNamespace
import pytest
import streamops.server.platform.windows.game_process as native
from streamops.server.platform.windows.game_process import WindowsGameProcess,GamePlatformError
from streamops.server.services.games.models import GameObservation,ProcessIdentity
from streamops.server.services.games.providers.static import StaticProvider

GAME=StaticProvider().discover()[0]
class Steam:
    def status(self): return SimpleNamespace(running=True,interactive=True)
    def resolve_installation(self,*,required=False): return Path("C:/Steam/steam.exe")

def subject(monkeypatch,root):
    platform=WindowsGameProcess(Steam())
    monkeypatch.setattr(platform,"_installed_dir",lambda game:root)
    return platform

def fake(pid,path,session=1,created=1000):
    return SimpleNamespace(pid=pid,path=path,session_id=session,started_at_timestamp=created)

def test_multiple_matching_processes_rejected(monkeypatch,tmp_path):
    p=subject(monkeypatch,tmp_path)
    monkeypatch.setattr(p,"_processes",lambda game:[fake(3,tmp_path/"Diablo IV.exe"),fake(4,tmp_path/"Diablo IV.exe")])
    with pytest.raises(GamePlatformError) as exc: p.inspect(GAME)
    assert exc.value.code=="game_identity_ambiguous"

def test_invalid_path_or_missing_identity_rejected(monkeypatch,tmp_path):
    p=subject(monkeypatch,tmp_path)
    monkeypatch.setattr(p,"_processes",lambda game:[fake(5,tmp_path.parent/"Other"/"Diablo IV.exe")])
    with pytest.raises(GamePlatformError) as exc: p.inspect(GAME)
    assert exc.value.code=="game_identity_ambiguous"
    monkeypatch.setattr(p,"_processes",lambda game:[fake(5,None)])
    with pytest.raises(GamePlatformError) as exc: p.inspect(GAME)
    assert exc.value.code=="game_status_unknown"

def test_wrong_console_session_is_unsafe(monkeypatch,tmp_path):
    p=subject(monkeypatch,tmp_path)
    monkeypatch.setattr(p,"_processes",lambda game:[fake(5,tmp_path/"Diablo IV.exe",session=2)])
    monkeypatch.setattr(native,"desktop_session_info",lambda:SimpleNamespace(active_console_session_id=1))
    with pytest.raises(GamePlatformError) as exc: p.inspect(GAME)
    assert exc.value.code=="wrong_desktop_session"

def test_pid_reuse_cannot_issue_wm_close(monkeypatch,tmp_path):
    p=subject(monkeypatch,tmp_path)
    monkeypatch.setattr(p,"_require_interactive",lambda:None)
    actual=ProcessIdentity(state="RUNNING",pid=10,session_id=1,created_at="later",executable="C:/Game/game.exe",stale=False)
    monkeypatch.setattr(p,"inspect",lambda game:GameObservation(process=actual))
    prior=actual.model_copy(update={"created_at":"earlier"})
    with pytest.raises(GamePlatformError) as exc: p.stop(GAME,prior)
    assert exc.value.code=="game_identity_ambiguous"

@pytest.mark.parametrize("axis,value",[
    ("window","FOREGROUND"),("window","BACKGROUND"),("window","UNKNOWN"),
    ("obsCapture","CONFIGURED_ONLY"),("obsCapture","UNKNOWN"),("obsCapture","ERROR"),
    ("selectedForStream","SELECTED"),("selectedForStream","NOT_SELECTED")])
def test_independent_axes_do_not_prove_running(axis,value):
    observed=GameObservation.model_validate({axis:value})
    assert observed.process.state=="UNKNOWN"
    assert observed.process.stale
    assert observed.owned is None and observed.installed is None

def test_absent_game_is_stopped_but_not_owned(monkeypatch,tmp_path):
    p=subject(monkeypatch,tmp_path)
    monkeypatch.setattr(p,"_processes",lambda game:[])
    observed=p.inspect(GAME)
    assert observed.process.state=="STOPPED"
    assert observed.installed is True and observed.owned is None
