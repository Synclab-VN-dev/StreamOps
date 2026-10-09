package com.synclab.d4planner.bridge

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.graphics.Typeface
import android.text.InputType
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.Switch
import android.widget.Toast
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.synclab.d4planner.bridge.capture.CaptureState
import com.synclab.d4planner.bridge.ack.AckConfig
import com.synclab.d4planner.bridge.ack.AckSettings

class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var reportView: TextView
    private val refresh = object : Runnable {
        override fun run() {
            if (::reportView.isInitialized) {
                reportView.text = CaptureState.report(CaptureState.controllerDevices())
            }
            handler.postDelayed(this, 400L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(20, 20, 20, 20)
        }
        val title = TextView(this).apply {
            text = "XC | Xbox Input Capture | #79"
            textSize = 22f
            setTypeface(null, Typeface.BOLD)
        }
        layout.addView(title)
        val help = TextView(this).apply {
            text = "1. Pair Xbox controller with Android C.\n" +
                "2. Enable Controller Bridge in Accessibility settings.\n" +
                "3. Open Steam Link, control Diablo IV and press buttons.\n" +
                "4. Return here; copy raw evidence and compare gameplay.\n" +
                "Only KeyEvents can be observed in this milestone. " +
                "DPAD may be delivered as MotionEvent and thus absent. " +
                "Never enable motion interception during this feasibility test."
            textSize = 14f
        }
        layout.addView(help)
        layout.addView(Button(this).apply {
            text = "Open Accessibility settings"
            setOnClickListener { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        })
        val actions = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
        }
        actions.addView(Button(this).apply {
            text = "Copy evidence"
            setOnClickListener {
                val content = CaptureState.report(CaptureState.controllerDevices())
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("XC #79 evidence", content))
            }
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        actions.addView(Button(this).apply {
            text = "Clear log"
            setOnClickListener {
                CaptureState.clearEvidence()
                reportView.text = CaptureState.report(CaptureState.controllerDevices())
            }
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        layout.addView(actions)

        val saved = AckSettings.load(this)
        layout.addView(TextView(this).apply {
            text = "Experimental ACK-before-forward: disabled unless explicitly enabled. " +
                "ACK must be committed on A before Android releases a key; " +
                "timeout/error ALWAYS fails open (Steam Link still receives it)."
            textSize = 12f
        })

        val targetRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
        }
        val hostInput = EditText(this).apply {
            setSingleLine(true)
            hint = "A LAN IPv4"
            inputType = InputType.TYPE_CLASS_TEXT
            setText(saved.host)
        }
        targetRow.addView(hostInput, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 2f))
        val portInput = EditText(this).apply {
            setSingleLine(true)
            hint = "Port"
            inputType = InputType.TYPE_CLASS_NUMBER
            setText(saved.port.toString())
        }
        targetRow.addView(portInput, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        layout.addView(targetRow)

        val tokenInput = EditText(this).apply {
            setSingleLine(true)
            hint = "XC_ACK_TOKEN on A (private)"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(saved.token)
        }
        layout.addView(tokenInput)

        val ackToggle = Switch(this).apply {
            text = "WAIT_ACK (experimental; default OFF)"
            isChecked = saved.enabled
        }
        val saveButton = Button(this).apply { text = "Save LAN ACK settings" }
        val currentSettings = { on: Boolean ->
            AckConfig(
                enabled = on,
                host = hostInput.text.toString().trim(),
                port = portInput.text.toString().toIntOrNull() ?: 0,
                token = tokenInput.text.toString()
            )
        }
        val status = TextView(this).apply {
            text = if (saved.enabled) "Mode: WAIT_ACK" else "Mode: OBSERVE_ONLY"
            textSize = 13f
        }
        ackToggle.setOnCheckedChangeListener { _, checked ->
            val cfg = currentSettings(checked)
            if (checked && !cfg.isValid()) {
                Toast.makeText(this, "Private LAN IPv4 + port >=1024 + token >=16 characters required", Toast.LENGTH_LONG).show()
                ackToggle.isChecked = false
            } else if (!AckSettings.save(this, cfg)) {
                Toast.makeText(this, "Cannot persist settings; mode stays unchanged", Toast.LENGTH_LONG).show()
                ackToggle.isChecked = false
            }
            val configured = AckSettings.load(this)
            status.text = if (configured.enabled) "Mode: WAIT_ACK" else "Mode: OBSERVE_ONLY"
        }
        saveButton.setOnClickListener {
            val cfg = currentSettings(ackToggle.isChecked)
            if (cfg.enabled && !cfg.isValid()) {
                Toast.makeText(this, "Invalid ACK configuration; turn WAIT_ACK off first", Toast.LENGTH_LONG).show()
            } else {
                val ok = AckSettings.save(this, cfg)
                Toast.makeText(this, if (ok) "ACK settings saved" else "Could not save settings", Toast.LENGTH_SHORT).show()
                val active = AckSettings.load(this)
                status.text = if (active.enabled) "Mode: WAIT_ACK" else "Mode: OBSERVE_ONLY"
            }
        }
        layout.addView(ackToggle)
        layout.addView(saveButton)
        layout.addView(status)

        reportView = TextView(this).apply {
            textSize = 12f
            typeface = Typeface.MONOSPACE
            setTextIsSelectable(true)
        }
        val scroll = ScrollView(this)
        scroll.addView(reportView)
        layout.addView(
            scroll, LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
            )
        )
        setContentView(layout)
    }

    override fun onStart() {
        super.onStart()
        handler.post(refresh)
    }

    override fun onStop() {
        handler.removeCallbacks(refresh)
        super.onStop()
    }
}
