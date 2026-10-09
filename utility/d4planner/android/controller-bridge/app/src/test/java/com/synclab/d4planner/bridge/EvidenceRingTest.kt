package com.synclab.d4planner.bridge

import com.synclab.d4planner.bridge.capture.EvidenceRing
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import kotlin.concurrent.thread

class EvidenceRingTest {
    @Test fun capacityDropsOldestWithoutBlocking() {
        val ring = EvidenceRing<Int>(3)
        (1..5).forEach(ring::offer)
        assertEquals(listOf(3, 4, 5), ring.snapshot())
        assertEquals(2L, ring.droppedCount())
    }

    @Test fun snapshotsCannotMutateHistory() {
        val ring = EvidenceRing<String>(2)
        ring.offer("A DOWN")
        val snapshot = ring.snapshot()
        ring.offer("A UP")
        assertEquals(listOf("A DOWN"), snapshot)
        assertEquals(listOf("A DOWN", "A UP"), ring.snapshot())
    }

    @Test fun concurrentWritesStayBounded() {
        val ring = EvidenceRing<Int>(100)
        val start = CountDownLatch(1)
        val workers = (0..3).map { worker ->
            thread {
                start.await()
                repeat(1000) { ring.offer(worker * 1000 + it) }
            }
        }
        start.countDown()
        workers.forEach { it.join() }
        assertEquals(100, ring.snapshot().size)
        assertEquals(3900L, ring.droppedCount())
    }

    @Test fun clearResetsEntriesAndOverflowCount() {
        val ring = EvidenceRing<Int>(2)
        ring.offer(10)
        ring.offer(11)
        ring.offer(12)
        assertEquals(1L, ring.droppedCount())
        ring.clear()
        assertTrue(ring.snapshot().isEmpty())
        assertEquals(0L, ring.droppedCount())
        ring.offer(99)
        assertEquals(listOf(99), ring.snapshot())
    }

    @Test(expected = IllegalArgumentException::class)
    fun zeroCapacityRejected() {
        EvidenceRing<Int>(0)
    }
}
