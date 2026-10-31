import pytest

from d4planner.runtime.model import RuntimeState, can_transition


def test_happy_path_state_transitions_are_allowed():
    path = [
        RuntimeState.STOPPED,
        RuntimeState.BOOTSTRAPPING,
        RuntimeState.NVDA_READY,
        RuntimeState.TOLK_READY,
        RuntimeState.GAME_STARTING,
        RuntimeState.GAME_ATTACHED,
        RuntimeState.CAPTURE_READY,
        RuntimeState.RUNNING,
    ]
    assert all(can_transition(a, b) for a, b in zip(path, path[1:]))


def test_invalid_ready_jump_is_rejected():
    assert not can_transition(RuntimeState.STOPPED, RuntimeState.RUNNING)
    assert not can_transition(RuntimeState.BOOTSTRAPPING, RuntimeState.RUNNING)


def test_runtime_can_move_to_safe_terminal_states():
    for state in RuntimeState:
        if state == RuntimeState.STOPPED:
            continue
        assert can_transition(state, RuntimeState.STOPPED) or state in {
            RuntimeState.BLOCKED,
            RuntimeState.RESTART_REQUIRED,
        }


def test_waiting_for_game_can_block_when_required_hook_fails():
    assert can_transition(RuntimeState.WAITING_FOR_GAME, RuntimeState.BLOCKED)
