//! S9 native orchestration; neither React paths nor GitHub App credentials cross this boundary.
use d4planner_report_issue::{Config, Description, Report, Selection};
use serde_json::Value;
use std::{env, fs, path::PathBuf, sync::Mutex};
static REPORT: Mutex<Option<Report>> = Mutex::new(None);
fn data_root() -> Result<PathBuf, String> {
    let logs = PathBuf::from(env::var("D4_LOG_DIR").map_err(|_| "LOG_SESSION_UNAVAILABLE")?);
    if !logs.is_absolute() || !d4planner_runtime_logging::safe(&logs) {
        return Err("INVALID_LOG_SESSION".into());
    }
    logs.parent()
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf())
        .ok_or("INVALID_LOG_SESSION".into())
}
fn config() -> Result<Config, String> {
    // Host provisioning only. No client defaults, private key, endpoint or recipient supplied by React.
    let path =
        PathBuf::from(env::var("D4PLANNER_REPORT_CONFIG").map_err(|_| "REPORT_NOT_CONFIGURED")?);
    if !path.is_absolute()
        || !d4planner_runtime_logging::safe(&path)
        || fs::metadata(&path)
            .map_err(|_| "REPORT_NOT_CONFIGURED")?
            .len()
            > 8192
    {
        return Err("INVALID_REPORT_CONFIG".into());
    }
    let config: Config =
        serde_json::from_slice(&fs::read(path).map_err(|_| "REPORT_NOT_CONFIGURED")?)
            .map_err(|_| "INVALID_REPORT_CONFIG")?;
    config.validate()?;
    Ok(config)
}
fn evidence(_destination: &std::path::Path) -> Result<Value, String> {
    // Existing logs --raw selects capture state, not the HUD run. No verified
    // packaged capture-session binding exists yet. Never guess or export a DB.
    Err("RAW_EVENT_SOURCE_NOT_BOUND".into())
}
#[tauri::command]
pub async fn collect_issue_report(selection: Selection) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut state = REPORT.lock().map_err(|_| "REPORT_BUSY")?;
        if state.as_ref().is_some_and(Report::pending_remote) {
            return Err("REPORT_RECONCILIATION_REQUIRED".into());
        }
        if let Some(old) = state.take() {
            old.discard()?;
        }
        let report = Report::collect(
            &data_root()?,
            &env::var("D4_LOG_RUN_ID").map_err(|_| "LOG_SESSION_UNAVAILABLE")?,
            selection,
            evidence,
        )?;
        let preview = report.preview.clone();
        *state = Some(report);
        Ok(preview)
    })
    .await
    .map_err(|_| "COLLECTION_FAILED")?
}
#[tauri::command]
pub async fn submit_issue_report(
    report_id: String,
    description: Description,
    consent: bool,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut state = REPORT.lock().map_err(|_| "REPORT_BUSY")?;
        let report = state.as_mut().ok_or("REPORT_NOT_COLLECTED")?;
        if report.id != report_id {
            return Err("STALE_REPORT".into());
        }
        let token =
            env::var("D4PLANNER_REPORT_ACCESS_TOKEN").map_err(|_| "AUTHENTICATION_REQUIRED")?;
        let result = report.submit(&config()?, &description, &token, consent)?;
        if let Some(old) = state.take() {
            old.discard()?;
        }
        Ok(result)
    })
    .await
    .map_err(|_| "SUBMISSION_FAILED")?
}
#[tauri::command]
pub fn cancel_issue_report() -> Result<(), String> {
    let mut state = REPORT.lock().map_err(|_| "REPORT_BUSY")?;
    if state.as_ref().is_some_and(Report::pending_remote) {
        return Err("REPORT_RECONCILIATION_REQUIRED".into());
    }
    if let Some(old) = state.take() {
        old.discard()?;
    }
    Ok(())
}
#[tauri::command]
pub fn resume_issue_report(report_id: String) -> Result<Value, String> {
    let mut state = REPORT.lock().map_err(|_| "REPORT_BUSY")?;
    if state.is_none() {
        *state = Some(Report::resume(&data_root()?, &report_id)?);
    }
    let report = state.as_ref().ok_or("REPORT_NOT_FOUND")?;
    if report.id != report_id {
        return Err("REPORT_BUSY".into());
    }
    Ok(report.restored_preview())
}
