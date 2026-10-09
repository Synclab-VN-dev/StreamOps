package com.synclab.d4planner.bridge.ack

/** Pure validation for the debug-only ADB Intent provisioning bridge. */
object AckProvisioning {
    const val ACTION_PROVISION = "com.synclab.d4planner.bridge.action.PROVISION_ACK"
    const val EXTRA_TOKEN = "com.synclab.d4planner.bridge.extra.ACK_TOKEN"

    /** Preserve destination and explicit WAIT_ACK mode; change ONLY valid token. */
    fun withToken(current: AckConfig, token: String?): AckConfig? =
        if (token != null && AckConfig.isValidToken(token)) {
            current.copy(token = token)
        } else null
}
