package com.synclab.d4planner.bridge.ack

import android.content.Context

/** App-private debug POC preferences; never print or include token in diagnostic exports. */
object AckSettings {
    private const val FILE_NAME = "xc_ack_poc"
    fun load(context: Context): AckConfig {
        val p = context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)
        val saved = AckConfig(
            enabled = p.getBoolean("enabled", false),
            host = p.getString("host", "192.168.1.8") ?: "192.168.1.8",
            port = p.getInt("port", 18795),
            token = p.getString("token", "") ?: ""
        )
        return if (saved.enabled && !saved.isValid()) saved.copy(enabled = false) else saved
    }

    fun save(context: Context, config: AckConfig): Boolean {
        if (config.enabled && !config.isValid()) return false
        return context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean("enabled", config.enabled)
            .putString("host", config.host)
            .putInt("port", config.port)
            .putString("token", config.token)
            .commit() // POC mode must persist before the UI advertises the change.
    }
}

