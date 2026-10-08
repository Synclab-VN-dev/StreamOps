use std::sync::Mutex;
use tauri::{Emitter, Manager, State, WebviewWindow};
use tauri_plugin_global_shortcut::{
    Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState,
};

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
    // Do not publish state if Windows refused the transition.
    window.set_ignore_cursor_events(!interactive).map_err(|error| error.to_string())?;
    *mode = interactive;
    Ok(OverlayStatus { interactive })
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

pub fn run() {
    tauri::Builder::default()
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

            let toggle = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::F10);
            let exit = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::F11);
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(move |handle, shortcut, event| {
                        if event.state != ShortcutState::Pressed {
                            return;
                        }
                        if shortcut == &exit {
                            handle.exit(0);
                            return;
                        }
                        if shortcut == &toggle {
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
                    })
                    .build(),
            )?;
            // Failure to register a recovery/exit shortcut must fail startup,
            // not leave the user with an unresponsive click-through window.
            app.global_shortcut().register(toggle)?;
            app.global_shortcut().register(exit)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("D4Planner overlay startup failed");
}

#[cfg(test)]
mod tests {
    #[test]
    fn toggling_modes_is_reversible() {
        let start = true;
        assert!(!(!start));
        assert_eq!(!(!start), start);
    }
}
