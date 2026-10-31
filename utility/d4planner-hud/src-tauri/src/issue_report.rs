//! S9 native orchestration; neither React paths nor GitHub App credentials cross this boundary.
use d4planner_report_issue::{Config, Description, Report, Selection};
use serde_json::Value;
use std::{
    env, fs,
    io::Read,
    path::PathBuf,
    process::{Command, Stdio},
    sync::Mutex,
    time::Duration,
};
use wait_timeout::ChildExt;
static EVIDENCE_CHILD: Mutex<Option<std::process::Child>> = Mutex::new(None);
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
fn evidence(destination: &std::path::Path) -> Result<Value, String> {
    let mut pending = EVIDENCE_CHILD.lock().map_err(|_| "EVIDENCE_BUSY")?;
    if let Some(child) = pending.as_mut() {
        if child
            .try_wait()
            .map_err(|_| "EVIDENCE_CLEANUP_PENDING")?
            .is_none()
        {
            return Err("EVIDENCE_CLEANUP_PENDING".into());
        }
        *pending = None;
    }
    let python = env::var("D4PLANNER_BACKEND_PYTHON").map_err(|_| "EVIDENCE_UNAVAILABLE")?;
    let mut command = Command::new(python);
    command
        .args([
            "-m",
            "d4planner.diagnostic_evidence",
            "--consent",
            "--destination",
        ])
        .arg(destination)
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|_| "EVIDENCE_UNAVAILABLE")?;
    let result = child.wait_timeout(Duration::from_secs(15));
    if !matches!(result, Ok(Some(_))) {
        let _ = child.kill();
        if !matches!(child.wait_timeout(Duration::from_secs(2)), Ok(Some(_))) {
            *pending = Some(child);
        }
        return Err("EVIDENCE_TIMEOUT".into());
    }
    let mut bytes = Vec::new();
    child
        .stdout
        .take()
        .ok_or("EVIDENCE_UNAVAILABLE")?
        .take(16_385)
        .read_to_end(&mut bytes)
        .map_err(|_| "EVIDENCE_UNAVAILABLE")?;
    if bytes.len() > 16_384 {
        return Err("EVIDENCE_UNAVAILABLE".into());
    }
    serde_json::from_slice(&bytes).map_err(|_| "EVIDENCE_UNAVAILABLE".into())
}
#[tauri::command]
pub async fn collect_issue_report(selection: Selection) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut state = REPORT.lock().map_err(|_| "REPORT_BUSY")?;
        if let Some(old) = state.take() {
            old.discard();
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
            old.discard();
        }
        Ok(result)
    })
    .await
    .map_err(|_| "SUBMISSION_FAILED")?
}
#[tauri::command]
pub fn cancel_issue_report() -> Result<(), String> {
    if let Some(old) = REPORT.lock().map_err(|_| "REPORT_BUSY")?.take() {
        old.discard();
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
