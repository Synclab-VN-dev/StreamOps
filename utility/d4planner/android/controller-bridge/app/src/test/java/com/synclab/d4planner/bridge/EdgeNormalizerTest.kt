package com.synclab.d4planner.bridge

import com.synclab.d4planner.bridge.capture.ControllerSource
import com.synclab.d4planner.bridge.capture.EdgeNormalizer
import org.junit.Assert.*
import org.junit.Test

class EdgeNormalizerTest {
    @Test fun downUpAndRepeatAreDistinct() {
        assertEquals("DOWN", EdgeNormalizer.action(0, 0))
        assertEquals("REPEAT", EdgeNormalizer.action(0, 2))
        assertEquals("UP", EdgeNormalizer.action(1, 0))
        assertEquals("UP", EdgeNormalizer.action(1, 4))
        assertEquals("UNKNOWN", EdgeNormalizer.action(2, 0))
    }

    @Test fun controllerSourceDetectionDoesNotCapturePlainKeyboard() {
        assertTrue(ControllerSource.isController(ControllerSource.GAMEPAD))
        assertTrue(ControllerSource.isController(ControllerSource.JOYSTICK))
        assertTrue(ControllerSource.isController(ControllerSource.GAMEPAD or 0x00000101))
        assertFalse(ControllerSource.isController(0x00000101)) // keyboard
        assertFalse(ControllerSource.isController(0x00001002)) // touchscreen
        assertFalse(ControllerSource.isController(0))
    }
}
