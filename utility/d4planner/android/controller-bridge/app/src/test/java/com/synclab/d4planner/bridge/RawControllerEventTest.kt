package com.synclab.d4planner.bridge

import com.synclab.d4planner.bridge.model.RawControllerEvent
import org.junit.Assert.*
import org.junit.Test

class RawControllerEventTest {
    @Test fun diagnosticRetainsRawIdentityAndBothClockSamples() {
        val event = RawControllerEvent(
            clientSeq = 582,
            sourceTimestampC = 9876543,
            captureTimestampC = 9876547,
            deviceId = 7,
            deviceName = "Example pad",
            vendorId = 1118,
            productId = 765,
            sources = 1025,
            source = 1025,
            keyCode = 96,
            scanCode = 304,
            action = 0,
            repeatCount = 0,
            edge = "DOWN",
            foregroundPackageAtCapture = "com.valvesoftware.steamlink"
        )
        val line = event.asDiagnosticLine()
        assertTrue(line.contains("#582"))
        assertTrue(line.contains("tC=9876543"))
        assertTrue(line.contains("captureC=9876547"))
        assertTrue(line.contains("DOWN"))
        assertTrue(line.contains("key=96"))
        assertTrue(line.contains("scan=304"))
        assertTrue(line.contains("device=7"))
        assertTrue(line.contains("foreground=com.valvesoftware.steamlink"))
        assertFalse(line.contains("Equip"))
    }
}
