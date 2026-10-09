package com.synclab.d4planner.bridge

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import com.synclab.d4planner.bridge.capture.CaptureState
import com.synclab.d4planner.bridge.ack.AckGate
import com.synclab.d4planner.bridge.ack.AckSettings

/**
 * Feasibility only. Returning false on EVERY path keeps events available to
 * Steam Link; this does not guarantee that Android will dispatch shared input.
 */
class ControllerAccessibilityService : AccessibilityService() {
    private val ackGate = AckGate()
    override fun onServiceConnected() {
        super.onServiceConnected()
        val config = serviceInfo
        config.flags = config.flags or AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
        serviceInfo = config
        CaptureState.setActive(true)
        CaptureState.setError("")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            CaptureState.setForegroundPackage(event.packageName?.toString())
        }
    }

    override fun onKeyEvent(event: KeyEvent): Boolean {
        try {
            val captured = CaptureState.observe(event)
            if (captured != null) {
                val config = AckSettings.load(this)
                if (config.enabled) {
                    CaptureState.recordAck(ackGate.waitForCommit(captured, config))
                }
            }
        } catch (failure: Exception) {
            CaptureState.setError("capture: " + failure.javaClass.simpleName + ": " + failure.message)
        }
        return false // NEVER consume input, including errors.
    }

    override fun onInterrupt() {
        CaptureState.setError("Accessibility service interrupted")
    }

    override fun onDestroy() {
        ackGate.close()
        CaptureState.setActive(false)
        super.onDestroy()
    }
}
