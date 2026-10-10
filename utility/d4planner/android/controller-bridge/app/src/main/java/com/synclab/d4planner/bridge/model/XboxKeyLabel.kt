package com.synclab.d4planner.bridge.model

/** Android KEYCODE_BUTTON_* constants, displayed as Xbox-friendly names. */
object XboxKeyLabel {
    fun forAndroidKeyCode(code: Int): String = when (code) {
        96 -> "A"
        97 -> "B"
        99 -> "X"
        100 -> "Y"
        102 -> "LB"
        103 -> "RB"
        104 -> "LT_KEY"
        105 -> "RT_KEY"
        106 -> "LS"
        107 -> "RS"
        108 -> "MENU"
        109 -> "VIEW"
        19 -> "DPAD_UP"
        20 -> "DPAD_DOWN"
        21 -> "DPAD_LEFT"
        22 -> "DPAD_RIGHT"
        else -> "KEY_$code"
    }
}
