import pytest

from d4planner.runtime.input_marker import edge_transition, virtual_key_code


def test_virtual_key_code_accepts_scroll_lock_aliases():
    assert virtual_key_code("scroll-lock") == 0x91
    assert virtual_key_code("SCROLL_LOCK") == 0x91


def test_virtual_key_code_rejects_unknown_key():
    with pytest.raises(ValueError):
        virtual_key_code("f24")


def test_edge_transition_only_emits_on_change():
    assert edge_transition(False, False) is None
    assert edge_transition(False, True) == "DOWN"
    assert edge_transition(True, True) is None
    assert edge_transition(True, False) == "UP"
