mod overlay_core;
mod backend_process;

use std::{collections::BTreeMap, env, fs, path::PathBuf, sync::{Arc, Mutex}, time::Duration};
use tauri::{Emitter, Manager, State, WebviewWindow};
use tauri_plugin_global_shortcut::GlobalShortcutExt;
use overlay_core::{exit_shortcut, shortcut_action, toggle_shortcut, transition_mode, ShortcutAction};
use backend_process::{BackendProcessWrapper, LaunchSpecification, ProcessState, ReadyInfo, StdProcessDriver};

const MODE_EVENT: &str = "overlay-mode-changed";

struct ModeState(Mutex<bool>);
struct BackendState(Mutex<Option<Arc<BackendProcessWrapper<StdProcessDriver>>>>);

#[derive(Clone, serde::Serialize)]
struct OverlayStatus {
    interactive: bool,
}

#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendStatus {
    state: ProcessState,
    ready: Option<ReadyInfo>,
}

fn required_env(name: &str) -> Result<String, String> {
    env::var(name).map_err(|_| format!("{name} is required by native Backend configuration"))
}

/// Native composition root. React cannot provide executable/path/credential
/// values; packaging supplies them through an owner-controlled environment.
fn backend_from_environment() -> Result<BackendProcessWrapper<StdProcessDriver>, String> {
    let executable = PathBuf::from(required_env("D4PLANNER_BACKEND_PYTHON")?);
    if !executable.is_absolute() || !executable.is_file() {
        return Err("D4PLANNER_BACKEND_PYTHON must be an absolute existing file".into());
    }
    let bootstrap_path = PathBuf::from(required_env("D4PLANNER_BOOTSTRAP_FILE")?);
    let bootstrap: serde_json::Value = serde_json::from_slice(
        &fs::read(&bootstrap_path).map_err(|error| format!("cannot read bootstrap descriptor: {error}"))?
    ).map_err(|error| format!("invalid bootstrap descriptor: {error}"))?;
    let string_field = |name: &str| bootstrap.get(name).and_then(|value| value.as_str())
        .map(str::to_owned).ok_or_else(|| format!("bootstrap {name} is missing"));
    let generation = bootstrap.get("generation").and_then(|value| value.as_u64())
        .ok_or("bootstrap generation is missing")?;
    let mut environment = BTreeMap::new();
    environment.insert("D4PLANNER_BOOTSTRAP_FILE".into(), bootstrap_path.to_string_lossy().into_owned());
    for name in ["SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PYTHONPATH"] {
        if let Ok(value) = env::var(name) { environment.insert(name.into(), value); }
    }
    Ok(BackendProcessWrapper::new(
        Arc::new(StdProcessDriver),
        LaunchSpecification {
            executable,
            args: vec!["-m".into(), "d4planner.managed_backend".into()],
            working_directory: env::current_dir().map_err(|error| error.to_string())?,
            environment,
            owner_instance_id: string_field("ownerInstanceId")?,
            child_instance_id: string_field("childInstanceId")?,
            generation,
            readiness_timeout: Duration::from_secs(15),
            graceful_stop_timeout: Duration::from_secs(5),
            kill_timeout: Duration::from_secs(3),
        },
    ))
}

#[tauri::command]
fn start_backend(state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let wrapper = {
        let mut slot = state.0.lock().map_err(|_| "Backend state lock poisoned")?;
        if slot.is_none() { *slot = Some(Arc::new(backend_from_environment()?)); }
        slot.as_ref().cloned().ok_or("Backend wrapper unavailable")?
    };
    let ready = wrapper.start()?;
    Ok(BackendStatus { state: wrapper.state(), ready: Some(ready) })
}

#[tauri::command]
fn stop_backend(state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let wrapper = state.0.lock().map_err(|_| "Backend state lock poisoned")?.clone();
    if let Some(wrapper) = wrapper {
        wrapper.stop()?;
        return Ok(BackendStatus { state: wrapper.state(), ready: None });
    }
    Ok(BackendStatus { state: ProcessState::Stopped, ready: None })
}

#[tauri::command]
fn get_backend_status(state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let wrapper = state.0.lock().map_err(|_| "Backend state lock poisoned")?.clone();
    Ok(match wrapper {
        Some(wrapper) => BackendStatus { state: wrapper.state(), ready: wrapper.ready_info() },
        None => BackendStatus { state: ProcessState::Stopped, ready: None },
    })
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
        .manage(BackendState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            get_overlay_status,
            set_overlay_mode,
            drag_overlay,
            start_backend,
            stop_backend,
            get_backend_status
        ])
        .setup(|app| {
            let window = app.get_webview_window("main").expect("configured main window");
            window.set_always_on_top(true)?;
            window.set_ignore_cursor_events(false)?;

            // Packaged S2 launches the managed Backend before the UI consumes
            // S5 data. Developer visual-only runs omit the bootstrap descriptor
            // and remain explicitly STOPPED rather than falling back to mock BE.
            if env::var_os("D4PLANNER_BOOTSTRAP_FILE").is_some() {
                let wrapper = Arc::new(backend_from_environment().map_err(std::io::Error::other)?);
                wrapper.start().map_err(std::io::Error::other)?;
                let state = app.state::<BackendState>();
                *state.0.lock().map_err(|_| std::io::Error::other("Backend state lock poisoned"))? = Some(wrapper);
            }

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
        if self_test && matches!(&event, tauri::RunEvent::Ready) {
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
        if matches!(&event, tauri::RunEvent::ExitRequested { .. }) {
            let state = handle.state::<BackendState>();
            if let Ok(slot) = state.0.lock() {
                if let Some(wrapper) = slot.clone() { let _ = wrapper.stop(); }
            }
        }
    });
}
