from d4planner.runtime.xinput import decode_buttons


def test_decode_xinput_buttons():
    assert decode_buttons(0) == ()
    assert decode_buttons(0x1000) == ("A",)
    assert decode_buttons(0x1000 | 0x0200 | 0x0008) == (
        "DPAD_RIGHT",
        "RIGHT_SHOULDER",
        "A",
    )
