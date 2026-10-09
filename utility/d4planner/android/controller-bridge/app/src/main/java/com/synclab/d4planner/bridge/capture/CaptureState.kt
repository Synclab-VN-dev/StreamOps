package com.synclab.d4planner.bridge.capture

import android.os.SystemClock
import android.view.InputDevice
import android.view.KeyEvent
import com.synclab.d4planner.bridge.model.RawControllerEvent
import java.util.concurrent.atomic.AtomicLong

/** Same-process ephemeral state, readable from activity after leaving Steam Link. */
object CaptureState {
    private const val CAPACITY = 512
    private val events = EvidenceRing<RawControllerEvent>(CAPACITY)
    private val counter = AtomicLong(0)

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
        val raw = RawControllerEvent(
            clientSeq = counter.incrementAndGet(),
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
            edge = EdgeNormalizer.action(event.action, event.repeatCount)
        )
        events.offer(raw)
    }

    fun report(devices: List<String>): String = buildString {
        appendLine("D4Planner Android Controller Bridge | Issue #79 | Milestone 1")
        appendLine("Read-only; no network; no injection")
        appendLine("serviceActive=" + serviceActive)
        appendLine("lastForegroundPackage=" + lastForegroundPackage)
        appendLine("clockDomain=android.uptimeMillis")
        appendLine("clientSeqHighWatermark=" + counter.get())
        appendLine("ringCapacity=" + CAPACITY)
        appendLine("ringDropped=" + events.droppedCount())
        if (lastError.isNotBlank()) appendLine("lastError=" + lastError)
        appendLine("Controller candidates:")
        if (devices.isEmpty()) appendLine("  (none)")
        devices.forEach { appendLine("  " + it) }
        appendLine("Recent raw events:")
        val snapshot = events.snapshot()
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
