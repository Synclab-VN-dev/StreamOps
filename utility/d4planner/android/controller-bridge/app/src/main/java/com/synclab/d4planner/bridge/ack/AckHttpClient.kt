package com.synclab.d4planner.bridge.ack

import android.os.SystemClock
import com.synclab.d4planner.bridge.model.RawControllerEvent
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Each request is self-contained. Retry is forbidden in the key callback. */
class AckHttpClient {
    data class Receipt(val status: String, val receiptSeq: Long? = null)

    fun send(event: RawControllerEvent, config: AckConfig): Receipt {
        val connection = URL("http://" + config.host + ":" + config.port + "/ack")
            .openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 15 // ms
            connection.readTimeout = 15 // ms
            connection.doOutput = true
            connection.useCaches = false
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("X-XC-Token", config.token)
            val payload = JSONObject()
                .put("version", 1)
                .put("sessionId", event.sessionId)
                .put("clientSeq", event.clientSeq)
                .put("sourceTimestampC", event.sourceTimestampC)
                .put("captureTimestampC", event.captureTimestampC)
                .put("sendTimestampC", SystemClock.uptimeMillis())
                .put("deviceId", event.deviceId)
                .put("vendorId", event.vendorId)
                .put("productId", event.productId)
                .put("sources", event.sources)
                .put("source", event.source)
                .put("keyCode", event.keyCode)
                .put("scanCode", event.scanCode)
                .put("action", event.action)
                .put("repeatCount", event.repeatCount)
                .put("edge", event.edge)
                .put("foreground", event.foregroundPackageAtCapture)
            val bytes = payload.toString().toByteArray(Charsets.UTF_8)
            connection.setFixedLengthStreamingMode(bytes.size)
            connection.outputStream.use { it.write(bytes) }

            if (connection.responseCode != 200) {
                return Receipt("HTTP_" + connection.responseCode + "_UNCONFIRMED")
            }
            val result = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            if (result.optString("status") != "COMMITTED" ||
                result.optString("sessionId") != event.sessionId ||
                result.optLong("clientSeq", -1) != event.clientSeq ||
                !result.has("receiptSeq")
            ) {
                return Receipt("INVALID_ACK_UNCONFIRMED")
            }
            return Receipt("COMMITTED", result.getLong("receiptSeq"))
        } finally {
            connection.disconnect()
        }
    }
}

