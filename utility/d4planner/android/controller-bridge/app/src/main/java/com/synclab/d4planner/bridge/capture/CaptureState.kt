package com.synclab.d4planner.bridge.capture

import android.os.SystemClock
import android.view.InputDevice
import android.view.KeyEvent
import com.synclab.d4planner.bridge.model.RawControllerEvent
import com.synclab.d4planner.bridge.ack.AckTrace
/** Same-process ephemeral state, readable from activity after leaving Steam Link. */
object CaptureState {
    private const val CAPACITY = 512
    private val history = CaptureHistory<RawControllerEvent>(CAPACITY)
    private val ackTraces = EvidenceRing<AckTrace>(128)
    private val foregroundHat = HatDiagnostics(128)

    @Volatile var serviceActive: Boolean = false
        private set
    @Volatile var lastForegroundPackage: String = "(unknown)"
        private set
    @Volatile var lastError: String = ""
        private set

    fun setActive(active: Boolean) {
        serviceActive = active
    }

    fun setForegroundPackage(value: String?) {
        if (!value.isNullOrBlank()) lastForegroundPackage = value
    }

    fun setError(value: String) {
        lastError = value
    }

    /** Snapshot synchronously. Never retain the framework-owned KeyEvent object. */
    fun observe(event: KeyEvent): RawControllerEvent? {
        val device = event.device
        val sources = (device?.sources ?: 0) or event.source
        if (!ControllerSource.isController(sources)) return null
        return history.recordReturning { session, nextSequence -> RawControllerEvent(
            clientSeq = nextSequence,
            sessionId = session,
            sourceTimestampC = event.eventTime,
            captureTimestampC = SystemClock.uptimeMillis(),
            deviceId = event.deviceId,
            deviceName = device?.name ?: "(unknown)",
            vendorId = device?.vendorId ?: 0,
            productId = device?.productId ?: 0,
            sources = sources,
            source = event.source,
            keyCode = event.keyCode,
            scanCode = event.scanCode,
            action = event.action,
            repeatCount = event.repeatCount,
            edge = EdgeNormalizer.action(event.action, event.repeatCount),
            foregroundPackageAtCapture = lastForegroundPackage
        ) }
    }

    /**
     * Called by the XC Activity only. NEVER register motion-source capture
     * in AccessibilityService, since Steam Link must retain its joystick input.
     */
    fun observeForegroundHat(
        eventTimeC: Long,
        captureTimeC: Long,
        deviceId: Int,
        deviceName: String,
        source: Int,
        x: Float,
        y: Float
    ) {
        foregroundHat.observe(
            HatSample(eventTimeC, captureTimeC, deviceId, deviceName, source, x, y)
        )
    }

    fun leaveXcForeground() {
        foregroundHat.resetActiveStates()
    }

    /** Safe to call while AccessibilityService continues receiving input. */
    fun clearEvidence() {
        history.clear()
        ackTraces.clear()
        foregroundHat.clear()
    }

    fun recordAck(trace: AckTrace) {
        ackTraces.offer(trace)
    }

    fun report(devices: List<String>): String = buildString {
        val evidence = history.snapshot()
        appendLine("D4Planner Android Controller Bridge | Issue #79 | Milestone 1")
        appendLine("Read-only; experimental LAN ACK mode available; no injection")
        appendLine("serviceActive=" + serviceActive)
        appendLine("lastForegroundPackage=" + lastForegroundPackage)
        appendLine("clockDomain=android.uptimeMillis")
        appendLine("captureSessionId=" + evidence.sessionId)
        appendLine("clientSeqHighWatermark=" + evidence.highWatermark)
        appendLine("ringCapacity=" + CAPACITY)
        appendLine("ringDropped=" + evidence.droppedCount)
        if (lastError.isNotBlank()) appendLine("lastError=" + lastError)
        appendLine("Controller candidates:")
        if (devices.isEmpty()) appendLine("  (none)")
        devices.forEach { appendLine("  " + it) }
        val hat = foregroundHat.snapshot()
        appendLine("XC foreground MotionEvent HAT diagnostic (LOCAL ONLY; NOT sent to A):")
        appendLine("hatSamplesObserved=" + hat.samplesObserved)
        appendLine("hatTransitionDropped=" + hat.droppedCount)
        appendLine("hatLastSample=" + (hat.lastSample?.diagnostic() ?: "(none)"))
        appendLine("Recent D-pad HAT transitions:")
        if (hat.transitions.isEmpty()) appendLine("  (none)")
        hat.transitions.forEach { appendLine("  " + it.diagnostic()) }
        appendLine("Recent raw KeyEvents:")
        val snapshot = evidence.entries
        if (snapshot.isEmpty()) appendLine("  (none)")
        snapshot.forEach { appendLine(it.asDiagnosticLine()) }
        appendLine("Recent ACK gate decisions (only when WAIT_ACK enabled):")
        ackTraces.snapshot().takeLast(40).forEach { appendLine("  " + it.diagnostic()) }
    }

    fun controllerDevices(): List<String> = InputDevice.getDeviceIds().asList().mapNotNull { id: Int ->
        val device = InputDevice.getDevice(id) ?: return@mapNotNull null
        if (!ControllerSource.isController(device.sources)) return@mapNotNull null
        "id=" + id + " name=" + device.name +
            " vendorId=" + device.vendorId + " productId=" + device.productId +
            " sources=0x" + device.sources.toString(16) +
            " descriptor=" + device.descriptor
    }
}
