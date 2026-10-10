package com.synclab.d4planner.bridge.capture

/**
 * Diagnostic samples from Android MotionEvents reaching XC's own foreground
 * Activity. This is NOT an AccessibilityService motion interceptor or LAN input.
 */
data class HatSample(
    val sourceTimestampC: Long, // MotionEvent.eventTime, Android C uptimeMillis
    val captureTimestampC: Long, // SystemClock.uptimeMillis on Android C
    val deviceId: Int,
    val deviceName: String,
    val source: Int,
    val rawHatX: Float,
    val rawHatY: Float
) {
    fun diagnostic(): String =
        "tC=$sourceTimestampC captureC=$captureTimestampC " +
            "hatX=$rawHatX hatY=$rawHatY device=$deviceId " +
            "src=0x${source.toString(16)} $deviceName"
}

data class HatTransition(val direction: String, val edge: String, val sample: HatSample) {
    fun diagnostic(): String = "DPAD_$direction $edge ${sample.diagnostic()}"
}

data class HatSnapshot(
    val samplesObserved: Long,
    val transitions: List<HatTransition>,
    val droppedCount: Long,
    val lastSample: HatSample?
)

/**
 * Emits only changes, including UP on return to center and UP + DOWN when
 * switching directly between opposite directions. Avoid logging every frame
 * of an analog joystick held down at 60 Hz.
 */
class HatDiagnostics(capacity: Int = 128) {
    private data class DirectionState(val horizontal: Int = 0, val vertical: Int = 0)
    private val lastByDevice = mutableMapOf<Int, DirectionState>()
    private val history = EvidenceRing<HatTransition>(capacity)
    private var samples = 0L
    private var last: HatSample? = null

    @Synchronized
    fun observe(sample: HatSample): List<HatTransition> {
        samples++
        last = sample
        val before = lastByDevice[sample.deviceId] ?: DirectionState()
        val after = DirectionState(
            horizontal = direction(sample.rawHatX),
            vertical = direction(sample.rawHatY)
        )
        val changes = mutableListOf<HatTransition>()
        if (before.horizontal != after.horizontal) {
            horizontal(before.horizontal)?.let { changes.add(HatTransition(it, "UP", sample)) }
            horizontal(after.horizontal)?.let { changes.add(HatTransition(it, "DOWN", sample)) }
        }
        if (before.vertical != after.vertical) {
            vertical(before.vertical)?.let { changes.add(HatTransition(it, "UP", sample)) }
            vertical(after.vertical)?.let { changes.add(HatTransition(it, "DOWN", sample)) }
        }
        changes.forEach(history::offer)
        lastByDevice[sample.deviceId] = after
        return changes
    }

    /** Reset held directions when XC leaves foreground; retain evidence. */
    @Synchronized
    fun resetActiveStates() {
        lastByDevice.clear()
    }

    @Synchronized
    fun clear() {
        lastByDevice.clear()
        history.clear()
        last = null
        samples = 0L
    }

    @Synchronized
    fun snapshot(): HatSnapshot =
        HatSnapshot(samples, history.snapshot(), history.droppedCount(), last)

    private fun direction(value: Float): Int = when {
        !value.isFinite() -> 0
        value >= 0.5f -> 1
        value <= -0.5f -> -1
        else -> 0
    }

    private fun horizontal(value: Int): String? = when (value) {
        -1 -> "LEFT"
         1 -> "RIGHT"
        else -> null
    }

    private fun vertical(value: Int): String? = when (value) {
        -1 -> "UP"
         1 -> "DOWN"
        else -> null
    }
}
