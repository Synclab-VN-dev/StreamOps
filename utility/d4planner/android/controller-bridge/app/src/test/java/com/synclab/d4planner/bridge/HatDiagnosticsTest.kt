package com.synclab.d4planner.bridge

import com.synclab.d4planner.bridge.capture.HatDiagnostics
import com.synclab.d4planner.bridge.capture.HatSample
import org.junit.Assert.*
import org.junit.Test

class HatDiagnosticsTest {
    private fun sample(
        x: Float = 0f,
        y: Float = 0f,
        device: Int = 15,
        sourceTime: Long = 100,
        captureTime: Long = 104
    ): HatSample = HatSample(
        sourceTimestampC = sourceTime,
        captureTimestampC = captureTime,
        deviceId = device,
        deviceName = "Xbox Wireless Controller",
        source = 0x1000010,
        rawHatX = x,
        rawHatY = y
    )

    @Test fun allFourDirectionsGenerateDownAndReleaseUp() {
        val diagnostics = HatDiagnostics()
        for ((x, y, expected) in listOf(
            Triple(0f, -1f, "UP"),
            Triple(0f, 1f, "DOWN"),
            Triple(-1f, 0f, "LEFT"),
            Triple(1f, 0f, "RIGHT")
        )) {
            assertEquals(listOf(expected to "DOWN"), diagnostics.observe(sample(x, y))
                .map { it.direction to it.edge })
            assertEquals(listOf(expected to "UP"), diagnostics.observe(sample())
                .map { it.direction to it.edge })
        }
        assertEquals(8, diagnostics.snapshot().transitions.size)
    }

    @Test fun heldHatDoesNotSpamEveryFrameAndOppositeDirectionsAreOrdered() {
        val diagnostics = HatDiagnostics()
        assertEquals(1, diagnostics.observe(sample(x = -1f)).size)
        repeat(500) { assertTrue(diagnostics.observe(sample(x = -1f)).isEmpty()) }
        assertEquals(
            listOf("LEFT" to "UP", "RIGHT" to "DOWN"),
            diagnostics.observe(sample(x = 1f)).map { it.direction to it.edge }
        )
        assertEquals(502L, diagnostics.snapshot().samplesObserved)
        assertEquals(3, diagnostics.snapshot().transitions.size)
    }

    @Test fun diagonalTracksTwoIndependentAxesWithRawTimestamps() {
        val diagnostics = HatDiagnostics()
        val event = sample(x = 1f, y = -1f, sourceTime = 1234567, captureTime = 1234569)
        val changes = diagnostics.observe(event)
        assertEquals(listOf("RIGHT" to "DOWN", "UP" to "DOWN"),
            changes.map { it.direction to it.edge })
        assertTrue(changes[0].diagnostic().contains("tC=1234567 captureC=1234569"))
        assertTrue(changes[0].diagnostic().contains("hatX=1.0 hatY=-1.0"))
        val release = diagnostics.observe(sample())
        assertEquals(listOf("RIGHT" to "UP", "UP" to "UP"),
            release.map { it.direction to it.edge })
    }

    @Test fun multipleDevicesAreIndependentAndThresholdRejectsNoise() {
        val diagnostics = HatDiagnostics()
        assertTrue(diagnostics.observe(sample(x = 0.1f, y = -0.3f)).isEmpty())
        assertEquals("LEFT", diagnostics.observe(sample(x = -0.8f, device = 16))[0].direction)
        assertTrue(diagnostics.observe(sample(device = 15)).isEmpty())
        assertEquals("LEFT", diagnostics.observe(sample(device = 16))[0].direction)
    }

    @Test fun boundedHistoryAndClearResetAllLocalEvidence() {
        val diagnostics = HatDiagnostics(capacity = 2)
        diagnostics.observe(sample(y = -1f))
        diagnostics.observe(sample())
        diagnostics.observe(sample(y = 1f))
        assertEquals(1L, diagnostics.snapshot().droppedCount)
        diagnostics.clear()
        assertEquals(0L, diagnostics.snapshot().samplesObserved)
        assertTrue(diagnostics.snapshot().transitions.isEmpty())
        assertNull(diagnostics.snapshot().lastSample)
        assertEquals(0L, diagnostics.snapshot().droppedCount)
        assertEquals("UP", diagnostics.observe(sample(y = -1f))[0].direction)
    }

    @Test fun inactiveStateResetPreventsStaleReleaseWhenReturningToXC() {
        val diagnostics = HatDiagnostics()
        diagnostics.observe(sample(y = -1f))
        diagnostics.resetActiveStates()
        assertTrue(diagnostics.observe(sample()).isEmpty())
        assertEquals(1, diagnostics.snapshot().transitions.size)
    }
}
