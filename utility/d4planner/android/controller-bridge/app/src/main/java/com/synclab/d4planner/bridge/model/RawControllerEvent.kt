package com.synclab.d4planner.bridge.model

/** Raw observations only. No guessed Xbox semantic or gameplay action. */
data class RawControllerEvent(
    val clientSeq: Long,
    val sourceTimestampC: Long, // Android KeyEvent.eventTime; uptimeMillis domain
    val captureTimestampC: Long, // Android SystemClock.uptimeMillis domain
    val deviceId: Int,
    val deviceName: String,
    val vendorId: Int,
    val productId: Int,
    val sources: Int,
    val source: Int,
    val keyCode: Int,
    val scanCode: Int,
    val action: Int,
    val repeatCount: Int,
    val edge: String
) {
    fun asDiagnosticLine(): String = buildString {
        append("#").append(clientSeq)
        append(" tC=").append(sourceTimestampC)
        append(" captureC=").append(captureTimestampC)
        append(" ").append(edge)
        append(" key=").append(keyCode)
        append(" scan=").append(scanCode)
        append(" repeat=").append(repeatCount)
        append(" device=").append(deviceId)
        append(" src=0x").append(source.toString(16))
        append(" ").append(deviceName)
    }
}
