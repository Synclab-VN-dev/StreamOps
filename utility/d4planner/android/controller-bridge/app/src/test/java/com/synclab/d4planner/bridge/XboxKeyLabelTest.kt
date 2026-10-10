package com.synclab.d4planner.bridge

import com.synclab.d4planner.bridge.model.XboxKeyLabel
import org.junit.Assert.assertEquals
import org.junit.Test

class XboxKeyLabelTest {
    @Test fun xboxBumpersHaveReadableNames() {
        assertEquals("LB", XboxKeyLabel.forAndroidKeyCode(102))
        assertEquals("RB", XboxKeyLabel.forAndroidKeyCode(103))
        assertEquals("A", XboxKeyLabel.forAndroidKeyCode(96))
        assertEquals("DPAD_DOWN", XboxKeyLabel.forAndroidKeyCode(20))
        assertEquals("KEY_999", XboxKeyLabel.forAndroidKeyCode(999))
    }
}
