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
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.synclab.d4planner.bridge.capture.CaptureState

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
