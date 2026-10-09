package com.synclab.d4planner.bridge

import com.synclab.d4planner.bridge.ack.AckConfig
import org.junit.Assert.*
import org.junit.Test

class AckConfigTest {
    @Test fun enabledMustHavePrivateIpv4AndSecret() {
        assertFalse(AckConfig(enabled = true).isValid())
        assertTrue(AckConfig(enabled = true, host = "192.168.1.8", token = "1234567890123456").isValid())
        assertTrue(AckConfig(enabled = true, host = "10.0.0.20", token = "1234567890123456").isValid())
        assertTrue(AckConfig(enabled = true, host = "172.31.1.20", token = "1234567890123456").isValid())
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

