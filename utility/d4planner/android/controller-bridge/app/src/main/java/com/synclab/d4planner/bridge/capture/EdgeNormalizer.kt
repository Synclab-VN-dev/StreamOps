package com.synclab.d4planner.bridge.capture

/** Pure functions: no input consumption and no Android runtime dependency. */
object EdgeNormalizer {
    fun action(action: Int, repeatCount: Int): String = when {
        action == 0 && repeatCount > 0 -> "REPEAT"
        action == 0 -> "DOWN"
        action == 1 -> "UP"
        else -> "UNKNOWN"
    }
}

/** InputDevice.SOURCE_GAMEPAD and SOURCE_JOYSTICK, extracted for JVM tests. */
object ControllerSource {
    const val GAMEPAD = 0x00000401
    const val JOYSTICK = 0x01000010
    fun isController(sources: Int): Boolean =
        (sources and GAMEPAD) == GAMEPAD ||
        (sources and JOYSTICK) == JOYSTICK
}
