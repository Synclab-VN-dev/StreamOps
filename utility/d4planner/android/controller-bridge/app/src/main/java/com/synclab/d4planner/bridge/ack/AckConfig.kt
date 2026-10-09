package com.synclab.d4planner.bridge.ack

/** Experimental LAN-only POC. This model has no Android dependency. */
data class AckConfig(
    val enabled: Boolean = false,
    val host: String = "192.168.1.8",
    val port: Int = 18795,
    val token: String = ""
) {
    fun isValid(): Boolean = isPrivateLanIpv4(host) && port in 1024..65535 &&
        isValidToken(token)

    companion object {
        fun isValidToken(token: String): Boolean =
            token.length in 16..256 && token.all { it.code in 33..126 }

        fun isPrivateLanIpv4(ip: String): Boolean {
            val parts = ip.split('.')
            if (parts.size != 4 || parts.any { it.isEmpty() || it.length > 3 || it.any { c -> c !in '0'..'9' } }) {
                return false
            }
            val bytes = parts.map { it.toIntOrNull() ?: return false }
            if (bytes.any { it !in 0..255 }) return false
            return bytes[0] == 10 ||
                (bytes[0] == 172 && bytes[1] in 16..31) ||
                (bytes[0] == 192 && bytes[1] == 168)
        }
    }
}

