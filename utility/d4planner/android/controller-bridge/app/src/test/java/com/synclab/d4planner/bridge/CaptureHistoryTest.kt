package com.synclab.d4planner.bridge

import com.synclab.d4planner.bridge.capture.CaptureHistory
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import kotlin.concurrent.thread

class CaptureHistoryTest {
    @Test fun clearingRetainsCaptureAndRestartsLocalPocSequence() {
        val history = CaptureHistory<Long>(2)
        repeat(3) { history.record { it } }
        val before = history.snapshot()
        assertEquals(3L, before.highWatermark)
        assertEquals(listOf(2L, 3L), before.entries)
        assertEquals(1L, before.droppedCount)

        history.clear()
        val cleared = history.snapshot()
        assertNotEquals(before.sessionId, cleared.sessionId)
        assertEquals(0L, cleared.highWatermark)
        assertEquals(0L, cleared.droppedCount)
        assertTrue(cleared.entries.isEmpty())

        history.record { it }
        assertEquals(listOf(1L), history.snapshot().entries)
        assertEquals(1L, history.snapshot().highWatermark)
    }

    @Test fun clearAndCallbackDoNotCreateDuplicateSequencesWithinNewRun() {
        val history = CaptureHistory<Long>(6000)
        val start = CountDownLatch(1)
        val worker = thread {
            start.await()
            repeat(1000) { history.record { it } }
        }
        start.countDown()
        history.clear()
        worker.join()
        val snapshot = history.snapshot()
        assertEquals(snapshot.entries.distinct(), snapshot.entries)
        assertEquals((1L..snapshot.highWatermark).toList(), snapshot.entries)
        assertEquals(0L, snapshot.droppedCount)
    }

    @Test fun recordReturningUsesSameSessionAndSequenceAsSnapshot() {
        val history = CaptureHistory<Pair<String, Long>>(8)
        val first = history.recordReturning { session, seq -> session to seq }
        assertEquals(history.snapshot().sessionId, first.first)
        assertEquals(1L, first.second)
        history.clear()
        val second = history.recordReturning { session, seq -> session to seq }
        assertNotEquals(first.first, second.first)
        assertEquals(1L, second.second)
    }
}
