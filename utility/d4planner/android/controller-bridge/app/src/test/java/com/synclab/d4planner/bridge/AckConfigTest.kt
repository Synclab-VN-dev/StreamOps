package com.synclab.d4planner.bridge

import com.synclab.d4planner.bridge.ack.AckConfig
import com.synclab.d4planner.bridge.ack.AckProvisioning
import org.junit.Assert.*
import org.junit.Test

class AckConfigTest {
    @Test fun enabledMustHavePrivateIpv4AndSecret() {
        assertFalse(AckConfig(enabled = true).isValid())
        assertTrue(AckConfig(enabled = true, host = "192.168.1.8", token = "1234567890123456").isValid())
        assertTrue(AckConfig(enabled = true, host = "10.0.0.20", token = "1234567890123456").isValid())
        assertTrue(AckConfig(enabled = true, host = "172.31.1.20", token = "1234567890123456").isValid())
    }
    @Test fun adbProvisioningPrefillsTokenWithoutChangingModeOrTarget() {
        val current = AckConfig(enabled = false, host = "192.168.1.8", port = 18795)
        val updated = AckProvisioning.withToken(current, "1234567890123456")
        assertNotNull(updated)
        assertFalse(updated!!.enabled)
        assertEquals("192.168.1.8", updated.host)
        assertEquals(18795, updated.port)
        assertEquals("1234567890123456", updated.token)
        assertNull(AckProvisioning.withToken(current, null))
        assertNull(AckProvisioning.withToken(current, "123"))
        assertNull(AckProvisioning.withToken(current, "123456789012345 "))
    }

    @Test fun adbProvisioningPreservesExplicitWaitAckMode() {
        val configured = AckConfig(enabled = true, token = "aaaaaaaaaaaaaaaa")
        val updated = AckProvisioning.withToken(configured, "bbbbbbbbbbbbbbbb")
        assertTrue(updated!!.enabled)
        assertEquals("bbbbbbbbbbbbbbbb", updated.token)
    }

    @Test fun refusesInternetAndUnsafeTargets() {
        for (host in listOf("8.8.8.8", "127.0.0.1", "example.com", "192.168.1.999",
            "192.168.1.8/32", "192.168.1.8:1", "172.32.1.1", "", "100.68.179.68")) {
            assertFalse(host, AckConfig(enabled = true, host = host, token = "1234567890123456").isValid())
        }
        assertFalse(AckConfig(enabled = true, port = 80, token = "1234567890123456").isValid())
        assertFalse(AckConfig(enabled = true, token = "short").isValid())
    }
}

