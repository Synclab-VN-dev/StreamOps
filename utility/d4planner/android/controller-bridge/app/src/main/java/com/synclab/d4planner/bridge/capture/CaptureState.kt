package com.synclab.d4planner.bridge.capture

import android.os.SystemClock
import android.view.InputDevice
import android.view.KeyEvent
import com.synclab.d4planner.bridge.model.RawControllerEvent
/** Same-process ephemeral state, readable from activity after leaving Steam Link. */
object CaptureState {
    private const val CAPACITY = 512
    private val history = CaptureHistory<RawControllerEvent>(CAPACITY)

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
    fun observe(event: KeyEvent) {
        val device = event.device
        val sources = (device?.sources ?: 0) or event.source
        if (!ControllerSource.isController(sources)) return
        history.record { nextSequence -> RawControllerEvent(
            clientSeq = nextSequence,
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

    /** Safe to call while AccessibilityService continues receiving input. */
    fun clearEvidence() {
        history.clear()
    }

    fun report(devices: List<String>): String = buildString {
        val evidence = history.snapshot()
        appendLine("D4Planner Android Controller Bridge | Issue #79 | Milestone 1")
        appendLine("Read-only; no network; no injection")
        appendLine("serviceActive=" + serviceActive)
        appendLine("lastForegroundPackage=" + lastForegroundPackage)
        appendLine("clockDomain=android.uptimeMillis")
        appendLine("clientSeqHighWatermark=" + evidence.highWatermark)
        appendLine("ringCapacity=" + CAPACITY)
        appendLine("ringDropped=" + evidence.droppedCount)
        if (lastError.isNotBlank()) appendLine("lastError=" + lastError)
        appendLine("Controller candidates:")
        if (devices.isEmpty()) appendLine("  (none)")
        devices.forEach { appendLine("  " + it) }
        appendLine("Recent raw events:")
        val snapshot = evidence.entries
        if (snapshot.isEmpty()) appendLine("  (none)")
        snapshot.forEach { appendLine(it.asDiagnosticLine()) }
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
