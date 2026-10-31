mod overlay_core;
mod hud_reader;
mod backend_process;

use std::{collections::BTreeMap, env, fs, path::PathBuf, sync::{Arc, Mutex}, time::Duration};
use tauri::{
    Emitter, LogicalSize, Manager, PhysicalPosition, Position, Size, State, WebviewWindow,
};
use tauri_plugin_global_shortcut::GlobalShortcutExt;
use overlay_core::{
    clamp_origin, exit_shortcut, shortcut_action, toggle_shortcut, transition_mode,
    validated_extent, ShortcutAction,
};
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

#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct HudWsBootstrap {
    endpoint: String,
    credential: String,
    origin: String,
}

fn required_env(name: &str) -> Result<String, String> {
    env::var(name).map_err(|_| format!("{name} is required by native Backend configuration"))
}

/// Native composition root. React cannot provide executable/path/credential
/// values; packaging supplies them through an owner-controlled environment.
fn backend_launch_from_environment() -> Result<LaunchSpecification, String> {
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
    let working_directory = env::current_dir().map_err(|error| error.to_string())?;
    let mut environment = BTreeMap::new();
    environment.insert("D4PLANNER_BOOTSTRAP_FILE".into(), bootstrap_path.to_string_lossy().into_owned());
    for name in ["SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PYTHONPATH"] {
        if let Ok(value) = env::var(name) { environment.insert(name.into(), value); }
    }
    for name in [
        "D4_RULEKIT_DATA_ROOT", "D4_RULEKIT_INSTALLATION_ROOT",
        "D4PLANNER_RULEKIT_EXECUTABLE", "D4PLANNER_RULEKIT_WORKER",
        "D4PLANNER_RULEKIT_WORKING_DIR", "D4_RULEKIT_PROFILE_JSON",
        "D4_RULEKIT_SNAPSHOT_ROOT", "D4_RULEKIT_CHROMIUM_EXECUTABLE",
        "D4_RULEKIT_MAX_CONTEXTS", "D4_RULEKIT_BROWSER_MAX_QUEUE",
        "D4_RULEKIT_MAX_SESSIONS", "D4_RULEKIT_SESSION_TTL_MS",
        "D4_RULEKIT_OPERATION_TIMEOUT_MS", "D4_RULEKIT_CLEANUP_TIMEOUT_MS",
        "D4PLANNER_EQUIPMENT_EVIDENCE_FILE",
        "D4PLANNER_EQUIPMENT_REPOSITORY_DB", "D4PLANNER_CHARACTER_ID",
        "D4PLANNER_CHARACTER_DISPLAY_NAME",
        "D4PLANNER_REPOSITORY_ROOT",
        "D4PLANNER_LATENCY_TRACE",
    ] {
        if let Ok(value) = env::var(name) { environment.insert(name.into(), value); }
    }
    // Packaged launches use the install root as their working directory. Keep
    // contract discovery explicit even when a Windows launcher does not
    // propagate the optional override into the native process environment.
    environment.entry("D4PLANNER_REPOSITORY_ROOT".into())
        .or_insert_with(|| working_directory.to_string_lossy().into_owned());
    Ok(LaunchSpecification {
            executable,
            args: vec!["-m".into(), "d4planner.managed_backend".into()],
            working_directory,
            environment,
            owner_instance_id: string_field("ownerInstanceId")?,
            child_instance_id: string_field("childInstanceId")?,
            generation,
            readiness_timeout: Duration::from_secs(15),
            graceful_stop_timeout: Duration::from_secs(5),
            kill_timeout: Duration::from_secs(3),
        })
}

fn backend_from_environment() -> Result<BackendProcessWrapper<StdProcessDriver>, String> {
    Ok(BackendProcessWrapper::new(
        Arc::new(StdProcessDriver), backend_launch_from_environment()?,
    ))
}

fn restart_ws_port(
    descriptor: &serde_json::Value, mode: Option<&str>, approved_port: Option<&str>,
) -> Result<u16, String> {
    match mode.unwrap_or("DYNAMIC") {
        "DYNAMIC" => Ok(0),
        "FIXED_APPROVED_UAT" => {
            let current = descriptor.pointer("/wsEndpoint/port")
                .and_then(serde_json::Value::as_u64)
                .and_then(|value| u16::try_from(value).ok())
                .filter(|value| *value != 0)
                .ok_or("fixed UAT restart requires a non-zero bootstrap port")?;
            let approved = approved_port
                .ok_or("D4PLANNER_APPROVED_UAT_PORT is required for fixed UAT restart")?
                .parse::<u16>().map_err(|_| "approved UAT port is invalid")?;
            if approved == 0 || approved != current {
                return Err("approved UAT port does not match bootstrap mapping".into());
            }
            Ok(current)
        }
        _ => Err("D4PLANNER_WS_PORT_MODE must be DYNAMIC or FIXED_APPROVED_UAT".into()),
    }
}

fn rotate_backend_bootstrap() -> Result<LaunchSpecification, String> {
    let path = PathBuf::from(required_env("D4PLANNER_BOOTSTRAP_FILE")?);
    let mut descriptor: serde_json::Value = serde_json::from_slice(
        &fs::read(&path).map_err(|error| format!("cannot read bootstrap descriptor: {error}"))?
    ).map_err(|error| format!("invalid bootstrap descriptor: {error}"))?;
    let generation = descriptor.get("generation").and_then(|value| value.as_u64())
        .ok_or("bootstrap generation is missing")? + 1;
    let credential: [u8; 32] = rand::random();
    descriptor["childInstanceId"] = serde_json::Value::String(uuid::Uuid::new_v4().to_string());
    descriptor["generation"] = serde_json::Value::from(generation);
    descriptor["credential"] = serde_json::Value::String(
        credential.iter().map(|byte| format!("{byte:02x}")).collect()
    );
    let restart_port = restart_ws_port(
        &descriptor,
        env::var("D4PLANNER_WS_PORT_MODE").ok().as_deref(),
        env::var("D4PLANNER_APPROVED_UAT_PORT").ok().as_deref(),
    )?;
    descriptor["wsEndpoint"] = serde_json::json!({"host":"127.0.0.1","port":restart_port});
    fs::write(&path, serde_json::to_vec(&descriptor).map_err(|error| error.to_string())?)
        .map_err(|error| format!("cannot rotate bootstrap descriptor: {error}"))?;
    backend_launch_from_environment()
}

/// Return the private loopback transport bootstrap only to this application
/// webview. The descriptor remains owned by the native composition root and
/// is never logged or exposed through a public HTTP endpoint.
#[tauri::command]
fn get_hud_ws_bootstrap(state: State<'_, BackendState>) -> Result<HudWsBootstrap, String> {
    let bootstrap_path = PathBuf::from(required_env("D4PLANNER_BOOTSTRAP_FILE")?);
    let bootstrap: serde_json::Value = serde_json::from_slice(
        &fs::read(&bootstrap_path)
            .map_err(|error| format!("cannot read bootstrap descriptor: {error}"))?,
    )
    .map_err(|error| format!("invalid bootstrap descriptor: {error}"))?;
    let wrapper = state.0.lock().map_err(|_| "Backend state lock poisoned")?.clone()
        .ok_or("managed Backend is not configured")?;
    let ready = wrapper.ready_info().ok_or("managed Backend is not READY")?;
    let host = ready.ws_endpoint.host.as_str();
    if !matches!(host, "127.0.0.1" | "::1" | "localhost") {
        return Err("bootstrap WebSocket endpoint must be loopback".into());
    }
    let port = ready.ws_endpoint.port;
    if port == 0 {
        return Err("managed Backend READY endpoint is not listening".into());
    }
    let credential = bootstrap
        .get("credential")
        .and_then(serde_json::Value::as_str)
        .filter(|value| value.len() >= 32)
        .ok_or("bootstrap credential is invalid")?
        .to_owned();
    let address = if host == "::1" { format!("[{host}]") } else { host.to_owned() };
    Ok(HudWsBootstrap {
        endpoint: format!("ws://{address}:{port}"),
        credential,
        origin: "tauri://localhost".into(),
    })
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
fn restart_backend(state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let wrapper = state.0.lock().map_err(|_| "Backend state lock poisoned")?.clone()
        .ok_or("managed Backend is not configured")?;
    let ready = wrapper.restart_with(rotate_backend_bootstrap()?)?;
    Ok(BackendStatus { state: wrapper.state(), ready: Some(ready) })
}

#[tauri::command]
fn get_backend_status(state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let wrapper = state.0.lock().map_err(|_| "Backend state lock poisoned")?.clone();
    Ok(match wrapper {
        Some(wrapper) => BackendStatus { state: wrapper.state(), ready: wrapper.ready_info() },
        None => BackendStatus { state: ProcessState::Stopped, ready: None },
    })
}

#[tauri::command]
async fn backend_command(state: State<'_, BackendState>, method: String, params: serde_json::Value) -> Result<serde_json::Value, String> {
    let wrapper = state.0.lock().map_err(|_| "Backend state lock poisoned")?.clone().ok_or("BACKEND_OFFLINE")?;
    tauri::async_runtime::spawn_blocking(move || wrapper.request(&method, params, Duration::from_secs(10)))
        .await.map_err(|_| "CONTROL_DISPATCH_FAILED".to_string())?
}

#[tauri::command]
async fn read_hud_database() -> Result<Option<serde_json::Value>, String> {
    let data_dir = PathBuf::from(env::var("D4PLANNER_DATA_DIR").map_err(|_| "CONFIGURATION_MISSING")?);
    tauri::async_runtime::spawn_blocking(move || hud_reader::read_latest(&data_dir))
        .await.map_err(|_| "DB_READ_FAILED".to_string())?
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

fn clamp_to_current_monitor(window: &WebviewWindow) -> Result<(), String> {
    let Some(monitor) = window.current_monitor().map_err(|error| error.to_string())? else {
        return Ok(());
    };
    let origin = window.outer_position().map_err(|error| error.to_string())?;
    let extent = window.outer_size().map_err(|error| error.to_string())?;
    let monitor_origin = monitor.position();
    let monitor_extent = monitor.size();
    let next = clamp_origin(
        (origin.x, origin.y),
        (extent.width, extent.height),
        (monitor_origin.x, monitor_origin.y),
        (monitor_extent.width, monitor_extent.height),
    );
    window.set_position(Position::Physical(PhysicalPosition::new(next.0, next.1)))
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn set_overlay_extent(window: WebviewWindow, width: u32, height: u32) -> Result<(), String> {
    let (width, height) = validated_extent(width, height)?;
    window.set_size(Size::Logical(LogicalSize::new(width as f64, height as f64)))
        .map_err(|error| error.to_string())?;
    clamp_to_current_monitor(&window)
}

#[tauri::command]
fn set_overlay_pin(window: WebviewWindow, pinned: bool) -> Result<(), String> {
    if !pinned {
        return Err("Release 1 Pin is always-on-top and cannot be disabled".into());
    }
    window.set_always_on_top(true).map_err(|error| error.to_string())
}

/// E2E-only observation sink. It cannot inject data or relax validation: the
/// webview must first receive a valid production WS snapshot and render model.
#[tauri::command]
fn report_hud_pipeline(
    app: tauri::AppHandle,
    snapshot: serde_json::Value,
    model_updated_at: String,
    ws_received_at: Option<String>,
    renderer_instance_id: String,
    visible_rendered_at: String,
) -> Result<(), String> {
    let path = env::var("D4_HUD_PIPELINE_REPORT")
        .map_err(|_| "HUD pipeline reporting is not enabled".to_string())?;
    let context = snapshot.pointer("/context/state").and_then(|value| value.as_str());
    let freshness = snapshot.pointer("/health/scoreFreshness").and_then(|value| value.as_str());
    let score = snapshot.pointer("/score/value").and_then(|value| value.as_f64());
    let revision = snapshot.get("hudRevision").and_then(|value| value.as_u64());
    let equipment = snapshot.get("equipment").and_then(|value| value.as_array());
    if context != Some("BOUND") || freshness != Some("CURRENT") || score.is_none()
        || revision.is_none() || equipment.is_none_or(|rows| rows.is_empty())
    {
        return Err("HUD pipeline snapshot is not render-ready".into());
    }
    let report = serde_json::json!({
        "ok": true, "contextState": context, "scoreFreshness": freshness,
        "score": score, "hudRevision": revision,
        "equipmentRows": equipment.map_or(0, Vec::len),
        "targetId": snapshot.pointer("/context/target/targetId"),
        "targetSha256": snapshot.pointer("/context/target/contentSha256"),
        "selectionRevision": snapshot.pointer("/context/target/selectionRevision"),
        "characterId": snapshot.pointer("/context/character/characterId"),
        "currentRevision": snapshot.pointer("/context/character/currentRevision"),
        "scoreStatus": snapshot.pointer("/score/status"),
        "failIssueCount": snapshot.pointer("/score/failIssueCount"),
        "warnCount": snapshot.pointer("/score/warnCount"),
        "itemsPassing": snapshot.pointer("/score/itemsPassing"),
        "itemsTargeted": snapshot.pointer("/score/itemsTargeted"),
        "modelUpdatedAt": model_updated_at,
        "wsReceivedAt": ws_received_at,
        "rendererInstanceId": renderer_instance_id,
        "visibleRenderedAt": visible_rendered_at,
    });
    fs::write(path, report.to_string()).map_err(|error| format!("cannot write HUD pipeline report: {error}"))?;
    if env::var_os("D4_HUD_PIPELINE_CONTINUOUS").is_none() {
        app.exit(0);
    }
    Ok(())
}

/// Private diagnostics for failures before React can mount. The path is only
/// enabled by the isolated acceptance environment and no credential or HUD
/// payload is accepted by this command.
#[tauri::command]
fn report_webview_diagnostic(phase: String, detail: Option<String>) -> Result<(), String> {
    use std::io::Write;
    let path = env::var("D4_WEBVIEW_DIAGNOSTIC_REPORT")
        .map_err(|_| "WebView diagnostics are not enabled".to_string())?;
    let record = serde_json::json!({
        "timestamp": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_millis(),
        "phase": phase,
        "detail": detail,
    });
    let mut file = fs::OpenOptions::new().create(true).append(true).open(path)
        .map_err(|error| format!("cannot open WebView diagnostic report: {error}"))?;
    writeln!(file, "{record}")
        .map_err(|error| format!("cannot write WebView diagnostic report: {error}"))
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

#[cfg(test)]
mod restart_port_tests {
    use super::restart_ws_port;

    fn descriptor(port: u16) -> serde_json::Value {
        serde_json::json!({"wsEndpoint":{"host":"127.0.0.1","port":port}})
    }

    #[test]
    fn dynamic_restart_requests_a_fresh_ephemeral_port() {
        assert_eq!(restart_ws_port(&descriptor(38150), None, None).unwrap(), 0);
        assert_eq!(restart_ws_port(&descriptor(38150), Some("DYNAMIC"), None).unwrap(), 0);
    }

    #[test]
    fn fixed_uat_restart_preserves_only_the_approved_mapping() {
        assert_eq!(
            restart_ws_port(&descriptor(38150), Some("FIXED_APPROVED_UAT"), Some("38150")).unwrap(),
            38150
        );
        assert!(restart_ws_port(&descriptor(38150), Some("FIXED_APPROVED_UAT"), None).is_err());
        assert!(restart_ws_port(&descriptor(38150), Some("FIXED_APPROVED_UAT"), Some("38151")).is_err());
        assert!(restart_ws_port(&descriptor(0), Some("FIXED_APPROVED_UAT"), Some("38150")).is_err());
    }

    #[test]
    fn unknown_restart_port_mode_fails_closed() {
        assert!(restart_ws_port(&descriptor(38150), Some("STATIC"), Some("38150")).is_err());
    }
}

pub fn run() {
    if env::args().any(|arg| arg == "--backend-self-test") {
        let result = (|| -> Result<serde_json::Value, String> {
            let specification = backend_launch_from_environment()?;
            let wrapper = BackendProcessWrapper::new(Arc::new(StdProcessDriver), specification.clone());
            let ready = wrapper.start()?;
            if ready.ws_endpoint.port == 0 || ready.health.ws_transport != "READY"
                || !["READY", "UNAVAILABLE"].contains(&ready.health.rule_kit_worker.as_str())
            {
                let _ = wrapper.stop();
                return Err("managed Backend service readiness is incomplete".into());
            }
            let restarted = wrapper.restart_with(rotate_backend_bootstrap()?)?;
            wrapper.stop()?;
            Ok(serde_json::json!({
                "ok":true,"ready":ready,"restartedReady":restarted,
                "finalState":wrapper.state()
            }))
        })();
        let report = match &result {
            Ok(value) => value.clone(),
            Err(error) => serde_json::json!({"ok":false,"error":error}),
        };
        let wrote = env::var("D4_BACKEND_SMOKE_REPORT").ok()
            .map(|path| fs::write(path, report.to_string()).is_ok()).unwrap_or(false);
        std::process::exit(if result.is_ok() && wrote { 0 } else { 1 });
    }
    let self_test = env::args().any(|arg| arg == "--self-test");
    let app = tauri::Builder::default()
        .manage(ModeState(Mutex::new(true)))
        .manage(BackendState(Mutex::new(None)))
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // Explicitly use the same owned shutdown path as the exit
                // hotkey. WebView/global-shortcut helper windows must not keep
                // the native runtime alive after its visible HUD is closed.
                api.prevent_close();
                eprintln!("Owned HUD close requested");
                window.app_handle().exit(0);
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_overlay_status,
            set_overlay_mode,
            drag_overlay,
            start_backend,
            stop_backend,
            restart_backend,
            get_backend_status,
            backend_command,
            read_hud_database,
            get_hud_ws_bootstrap,
            set_overlay_extent,
            set_overlay_pin,
            report_hud_pipeline,
            report_webview_diagnostic
        ])
        .setup(|app| {
            let window = app.get_webview_window("main").expect("configured main window");
            window.set_always_on_top(true)?;
            window.set_ignore_cursor_events(false)?;
            clamp_to_current_monitor(&window).map_err(std::io::Error::other)?;

            // Viewer-only is the default and has no Backend bootstrap dependency.
            // Integrated startup uses the same wrapper; a failed child never
            // prevents creation of the FE window or reading persisted HUD data.
            if env::var("D4PLANNER_MODE").as_deref() == Ok("integrated") {
                match backend_from_environment() {
                    Ok(wrapper) => {
                        let wrapper = Arc::new(wrapper);
                        let state = app.state::<BackendState>();
                        *state.0.lock().map_err(|_| std::io::Error::other("Backend state lock poisoned"))? = Some(wrapper.clone());
                        if wrapper.start().is_err() {
                            eprintln!("Managed Backend unavailable; viewer remains open");
                        }
                    }
                    Err(_) => eprintln!("Managed Backend configuration unavailable; viewer remains open"),
                }
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
            eprintln!("Owned HUD exit requested");
            let state = handle.state::<BackendState>();
            // Clone the owned wrapper out of the slot before the guard is
            // dropped. This avoids extending the temporary guard to the end
            // of the event block and never holds BackendState while stop waits.
            let wrapper = state.0.lock().ok().and_then(|slot| slot.clone());
            if let Some(wrapper) = wrapper {
                if let Err(error) = wrapper.stop() {
                    eprintln!("Owned Backend shutdown failed: {error}");
                } else {
                    eprintln!("Owned Backend shutdown complete");
                }
            }
        }
    });
}
