package com.synclab.d4planner.bridge.capture

/** Thread-safe bounded diagnostic history; no disk writes. */
class EvidenceRing<T>(private val capacity: Int) {
    init { require(capacity > 0) }
    private val entries = ArrayDeque<T>()
    private var dropped = 0L

    @Synchronized
    fun offer(value: T) {
        if (entries.size == capacity) {
            entries.removeFirst()
            dropped++
        }
        entries.addLast(value)
    }

    @Synchronized
    fun snapshot(): List<T> = entries.toList()

    @Synchronized
    fun droppedCount(): Long = dropped
}
