package com.synclab.d4planner.bridge.capture

/** One coherent snapshot even while a background observer records events. */
data class CaptureSnapshot<T>(
    val highWatermark: Long,
    val droppedCount: Long,
    val entries: List<T>
)

/**
 * The callback and Clear log button share this lock: no event can be inserted
 * between clearing the ring and resetting local sequence numbers.
 */
class CaptureHistory<T>(capacity: Int) {
    private val ring = EvidenceRing<T>(capacity)
    private var nextSequence = 0L

    @Synchronized
    fun record(create: (Long) -> T) {
        val seq = nextSequence + 1
        val event = create(seq)
        ring.offer(event)
        nextSequence = seq
    }

    @Synchronized
    fun clear() {
        ring.clear()
        nextSequence = 0L
    }

    @Synchronized
    fun snapshot(): CaptureSnapshot<T> =
        CaptureSnapshot(nextSequence, ring.droppedCount(), ring.snapshot())
}
