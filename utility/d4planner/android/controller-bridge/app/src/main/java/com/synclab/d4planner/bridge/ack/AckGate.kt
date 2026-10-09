package com.synclab.d4planner.bridge.ack

import android.os.SystemClock
import com.synclab.d4planner.bridge.model.RawControllerEvent
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ExecutionException
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

data class AckTrace(
    val sessionId: String,
    val clientSeq: Long,
    val outcome: String,
    val waitMs: Long,
    val receiptSeq: Long? = null
) {
    fun diagnostic(): String =
        "session=" + sessionId.take(8) + " #" + clientSeq +
        " ack=" + outcome + " waitMs=" + waitMs +
        (if (receiptSeq == null) "" else " receiptSeq=" + receiptSeq)
}

/**
 * The KeyEvent callback may run on Android's service main thread. A single
 * bounded worker handles I/O; Future.get has a STRICT 35 ms budget.
 * Returning false is unconditional even if an ACK never arrives.
 */
class AckGate {
    private val pool = ThreadPoolExecutor(
        1, 1, 0, TimeUnit.MILLISECONDS,
        ArrayBlockingQueue(1),
        { runnable -> Thread(runnable, "xc-ack-io").apply { isDaemon = true } },
        ThreadPoolExecutor.AbortPolicy()
    )
    private val client = AckHttpClient()

    fun waitForCommit(event: RawControllerEvent, config: AckConfig): AckTrace {
        if (!config.enabled) return AckTrace(event.sessionId, event.clientSeq, "OBSERVE_ONLY", 0)
        if (!config.isValid()) return AckTrace(event.sessionId, event.clientSeq, "INVALID_CONFIG", 0)
        val started = SystemClock.elapsedRealtimeNanos()
        val future = try {
            pool.submit<AckHttpClient.Receipt> { client.send(event, config) }
        } catch (_: RejectedExecutionException) {
            return AckTrace(event.sessionId, event.clientSeq, "WORKER_BUSY_UNCONFIRMED", 0)
        }

        return try {
            val receipt = future.get(35, TimeUnit.MILLISECONDS)
            AckTrace(
                event.sessionId, event.clientSeq, receipt.status,
                elapsedMillis(started), receipt.receiptSeq
            )
        } catch (_: TimeoutException) {
            future.cancel(true)
            AckTrace(event.sessionId, event.clientSeq, "TIMEOUT_UNCONFIRMED", elapsedMillis(started))
        } catch (_: InterruptedException) {
            future.cancel(true)
            Thread.currentThread().interrupt()
            AckTrace(event.sessionId, event.clientSeq, "INTERRUPTED_UNCONFIRMED", elapsedMillis(started))
        } catch (_: ExecutionException) {
            AckTrace(event.sessionId, event.clientSeq, "NETWORK_ERROR_UNCONFIRMED", elapsedMillis(started))
        }
    }

    private fun elapsedMillis(started: Long): Long =
        ((SystemClock.elapsedRealtimeNanos() - started).coerceAtLeast(0)) / 1_000_000L

    fun close() {
        pool.shutdownNow()
    }
}

