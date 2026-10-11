"""Issue 87 multi-key foreground/overflow/BLOCK policy regression."""
from d4planner.runtime.keyboard_hook import (
    BoundedSamples, WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN,
    capture_or_pass, decide_marker, VK_F11,
)

KEYS = frozenset((0x7A, 0x7B, 0x79, 0x78, 0xDB, 0xDD, 0xDC, 0xC0))


def test_multi_key_policy_foreground_and_observe_vs_block():
    for vk in KEYS:
        block = decide_marker(
            n_code=0, message=WM_KEYDOWN, vk=vk,
            foreground_pid=77, game_pid=77, block=True, virtual_keys=KEYS,
        )
        observe = decide_marker(
            n_code=0, message=WM_KEYUP, vk=vk,
            foreground_pid=77, game_pid=77, block=False, virtual_keys=KEYS,
        )
        assert block.capture and block.suppress and block.state == "down"
        assert observe.capture and not observe.suppress and observe.state == "up"
        assert not decide_marker(n_code=0, message=WM_KEYDOWN, vk=vk,
                                 foreground_pid=2, game_pid=77,
                                 block=True, virtual_keys=KEYS).suppress
    assert not decide_marker(n_code=0, message=WM_KEYDOWN, vk=0x41,
                             foreground_pid=77, game_pid=77,
                             block=True, virtual_keys=KEYS).capture


def test_capture_all_configured_keys_and_never_swallow_unrecorded_event():
    samples = BoundedSamples(capacity=3)
    for i, vk in enumerate((0x7A, 0x7B, 0x79)):
        assert capture_or_pass(
            n_code=0, message=WM_SYSKEYDOWN if i == 1 else WM_KEYDOWN,
            vk=vk, flags=0, foreground_pid=77, game_pid=77, block=True,
            samples=samples, timestamp_ms=100+i, virtual_keys=KEYS,
            scan_code=i+1,
        )
    assert not capture_or_pass(n_code=0, message=WM_KEYDOWN, vk=0x78, flags=0,
                               foreground_pid=77, game_pid=77, block=True,
                               samples=samples, timestamp_ms=104, virtual_keys=KEYS)
    assert samples.dropped == 1
    observed = samples.drain()
    assert [s.virtual_key for s in observed] == [0x7A, 0x7B, 0x79]
    assert [s.scan_code for s in observed] == [1, 2, 3]
    assert all(s.suppressed for s in observed)


def test_legacy_f11_only_by_default_and_unknown_key_passthrough():
    q = BoundedSamples()
    assert not capture_or_pass(n_code=0, message=WM_KEYDOWN, vk=0x79,
                               flags=0, foreground_pid=77, game_pid=77,
                               block=True, samples=q, timestamp_ms=100)
    assert capture_or_pass(n_code=0, message=WM_KEYDOWN, vk=VK_F11,
                           flags=0, foreground_pid=77, game_pid=77,
                           block=True, samples=q, timestamp_ms=100)
    assert len(q.drain()) == 1
