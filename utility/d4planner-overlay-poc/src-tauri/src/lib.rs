mod overlay_core;

use std::{env, fs, sync::Mutex};
use tauri::{Emitter, Manager, State, WebviewWindow};
use tauri_plugin_global_shortcut::GlobalShortcutExt;
use overlay_core::{exit_shortcut, shortcut_action, toggle_shortcut, transition_mode, ShortcutAction};

const MODE_EVENT: &str = "overlay-mode-changed";

struct ModeState(Mutex<bool>);

#[derive(Clone, serde::Serialize)]
struct OverlayStatus {
    interactive: bool,
}

fn read_mode(state: &ModeState) -> Result<bool, String> {
    state.0.lock().map(|mode| *mode).map_err(|_| "mode lock poisoned".to_string())
}

fn apply_mode(
    window: &WebviewWindow,
    state: &ModeState,
    interactive: bool,
) -> Result<OverlayStatus, String> {
    let mut mode = state.0.lock().map_err(|_| "mode lock poisoned".to_string())?;
    transition_mode(&mut mode, interactive, |ignore| {
        window.set_ignore_cursor_events(ignore).map_err(|error| error.to_string())
    })?;
    Ok(OverlayStatus { interactive: *mode })
}

#[tauri::command]
fn get_overlay_status(state: State<'_, ModeState>) -> Result<OverlayStatus, String> {
    Ok(OverlayStatus { interactive: read_mode(&state)? })
}

#[tauri::command]
fn set_overlay_mode(
    window: WebviewWindow,
    state: State<'_, ModeState>,
    interactive: bool,
) -> Result<OverlayStatus, String> {
    let result = apply_mode(&window, &state, interactive)?;
    window.emit(MODE_EVENT, result.clone()).map_err(|error| error.to_string())?;
    Ok(result)
}

#[tauri::command]
fn drag_overlay(window: WebviewWindow, state: State<'_, ModeState>) -> Result<(), String> {
    if !read_mode(&state)? {
        return Err("cannot drag while click-through is enabled".into());
    }
    window.start_dragging().map_err(|error| error.to_string())
}

/// Actual Tauri + native-window smoke. Requires a Windows desktop session.
/// It exercises OS APIs rather than just validating the executable's PE header.
fn runtime_smoke(handle: &tauri::AppHandle) -> Result<Vec<String>, String> {
    let window = handle.get_webview_window("main").ok_or("main window missing")?;
    let mut checks = Vec::new();

    if !window.is_always_on_top().map_err(|e| e.to_string())? {
        return Err("window is not always-on-top".into());
    }
    checks.push("always-on-top".into());

    if window.is_decorated().map_err(|e| e.to_string())? {
        return Err("window unexpectedly has decorations".into());
    }
    checks.push("frameless".into());

    if window.is_resizable().map_err(|e| e.to_string())? {
        return Err("window unexpectedly resizable".into());
    }
    checks.push("fixed-size".into());

    if window.is_fullscreen().map_err(|e| e.to_string())? {
        return Err("window unexpectedly fullscreen".into());
    }
    checks.push("not-fullscreen".into());

    let toggle = toggle_shortcut();
    let exit = exit_shortcut();
    if !handle.global_shortcut().is_registered(toggle) || !handle.global_shortcut().is_registered(exit) {
        return Err("required recovery hotkeys not registered".into());
    }
    checks.push("global-hotkeys-registered".into());

    let state = handle.state::<ModeState>();
    if !read_mode(&state)? {
        return Err("overlay must start interactive for recovery".into());
    }
    for interactive in [false, true, false, true] {
        let status = apply_mode(&window, &state, interactive)?;
        if status.interactive != interactive || read_mode(&state)? != interactive {
            return Err("OS/window mode and cached mode did not reconcile".into());
        }
    }
    checks.push("native-click-through-roundtrip".into());

    // Never leave the test window in passive mode.
    apply_mode(&window, &state, true)?;
    checks.push("interactive-recovered".into());
    Ok(checks)
}

pub fn run() {
    let self_test = env::args().any(|arg| arg == "--self-test");
    let app = tauri::Builder::default()
        .manage(ModeState(Mutex::new(true)))
        .invoke_handler(tauri::generate_handler![
            get_overlay_status,
            set_overlay_mode,
            drag_overlay
        ])
        .setup(|app| {
            let window = app.get_webview_window("main").expect("configured main window");
            window.set_always_on_top(true)?;
            window.set_ignore_cursor_events(false)?;

            let toggle = toggle_shortcut();
            let exit = exit_shortcut();
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(move |handle, shortcut, event| {
                        match shortcut_action(shortcut, event.state, &toggle, &exit) {
                            Some(ShortcutAction::Exit) => handle.exit(0),
                            Some(ShortcutAction::Toggle) => {
                                if let Some(window) = handle.get_webview_window("main") {
                                    let state = handle.state::<ModeState>();
                                    if let Ok(current) = read_mode(&state) {
                                        match apply_mode(&window, &state, !current) {
                                            Ok(status) => { let _ = handle.emit(MODE_EVENT, status); }
                                            Err(error) => eprintln!("Overlay toggle failed: {error}"),
                                        }
                                    }
                                }
                            }
                            None => {}
                        }
                    })
                    .build(),
            )?;
            // Fail closed at startup if a recovery hotkey is taken.
            app.global_shortcut().register(toggle)?;
            app.global_shortcut().register(exit)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("D4Planner overlay startup failed");

    app.run(move |handle, event| {
        if self_test && matches!(event, tauri::RunEvent::Ready) {
            let result = runtime_smoke(handle);
            let report = match &result {
                Ok(checks) => serde_json::json!({"ok":true,"checks":checks}),
                Err(error) => serde_json::json!({"ok":false,"error":error}),
            };
            let write_ok = env::var("D4_OVERLAY_SMOKE_REPORT")
                .ok()
                .filter(|path| !path.is_empty())
                .map(|path| fs::write(path, report.to_string()).is_ok())
                .unwrap_or(false);
            if !write_ok {
                eprintln!("Could not write smoke report");
            }
            if let Err(error) = &result {
                eprintln!("Overlay runtime smoke FAILED: {error}");
            }
            handle.exit(if result.is_ok() && write_ok { 0 } else { 1 });
        }
    });
}
