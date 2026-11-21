//! S9 native orchestration; neither React paths nor GitHub App credentials cross this boundary.
use d4planner_report_issue::{Description, Selection, SubmissionFailure};
use serde_json::Value;
use std::{env, path::PathBuf, sync::Mutex};
static REPORT: Mutex<d4planner_report_issue::coordinator::Coordinator> =
    Mutex::new(d4planner_report_issue::coordinator::Coordinator::new());
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
pub fn collect(
    actor: &str,
    selection: Selection,
    images: Vec<d4planner_report_issue::images::ImageInput>,
    image_consent: bool,
    capture_session: impl FnMut() -> Result<String,String>,
) -> Result<Value, String> {
    REPORT
        .try_lock()
        .map_err(|_| "REPORT_BUSY")?
        .collect_with_images(
            &data_root()?,
            &env::var("D4_LOG_RUN_ID").map_err(|_| "LOG_SESSION_UNAVAILABLE")?,
            actor,
            selection,
            &images,
            image_consent,
            |destination| d4planner_report_issue::events::export(&data_root()?, destination, capture_session),
        )
}
pub fn status(actor: &str, id: &str) -> Result<Value, String> {
    REPORT
        .try_lock()
        .map_err(|_| "REPORT_BUSY")?
        .status(&data_root()?, actor, id)
}
pub fn cancel(actor: &str, id: Option<&str>) -> Result<(), String> {
    REPORT
        .try_lock()
        .map_err(|_| "REPORT_BUSY")?
        .cancel(&data_root()?, actor, id)
}
pub fn submit(
    actor: &str,
    id: &str,
    description: Description,
    consent: bool,
) -> Result<Value, SubmissionFailure> {
    let root = data_root().map_err(SubmissionFailure::uncertain)?;
    REPORT
        .try_lock()
        .map_err(|_| SubmissionFailure::uncertain("REPORT_BUSY"))?
        .submit(
            &root,
            actor,
            id,
            description,
            consent,
            |report, description, consent| {
                if !consent || description.validate().is_err() {
                    return report.attempt(
                        Err("INVALID_REPORT_CONFIG".into()),
                        Err("AUTHENTICATION_REQUIRED".into()),
                        description,
                        consent,
                    );
                }
                let gateway = (|| {
                    let python = PathBuf::from(
                        env::var("D4PLANNER_BACKEND_PYTHON")
                            .map_err(|_| "LOCAL_GATEWAY_UNAVAILABLE")?,
                    );
                    d4planner_report_issue::local_gateway::LocalGateway::start(&python, &root)
                })();
                match gateway {
                    Ok(gateway) => report.attempt(
                        gateway.config(),
                        Ok(gateway.credential().to_owned()),
                        description,
                        consent,
                    ),
                    Err(code) => report.attempt(Err(code.clone()), Err(code), description, consent),
                }
            },
        )
}
#[tauri::command]
pub async fn collect_issue_report(
    state: tauri::State<'_, crate::BackendState>,
    selection: Selection,
    images: Option<Vec<d4planner_report_issue::images::ImageInput>>,
    image_consent: Option<bool>,
) -> Result<Value, String> {
    let wrapper = state.0.lock().map_err(|_| "BACKEND_OFFLINE")?.clone();
    tauri::async_runtime::spawn_blocking(move || {
        collect(
            "desktop",
            selection,
            images.unwrap_or_default(),
            image_consent.unwrap_or(false),
            || capture_session(wrapper.as_deref()),
        )
    })
    .await
    .map_err(|_| "COLLECTION_FAILED")?
}
#[tauri::command]
pub async fn submit_issue_report(
    report_id: String,
    description: Description,
    consent: bool,
) -> Result<Value, SubmissionFailure> {
    tauri::async_runtime::spawn_blocking(move || {
        submit("desktop", &report_id, description, consent)
    })
    .await
    .map_err(|_| SubmissionFailure::uncertain("SUBMISSION_FAILED"))?
}
#[tauri::command]
pub fn cancel_issue_report() -> Result<(), String> {
    cancel("desktop", None)
}
#[tauri::command]
pub fn resume_issue_report(report_id: String) -> Result<Value, String> {
    status("desktop", &report_id)
}

// Called only if evidence and separate raw-data consent were selected.
pub fn capture_session(wrapper: Option<&crate::BackendProcessWrapper<crate::StdProcessDriver>>) -> Result<String,String> {
    let wrapper = wrapper.ok_or("EVENT_SESSION_UNAVAILABLE")?;
    let value = wrapper.request("runtime.status", serde_json::json!({}), std::time::Duration::from_secs(5))
        .map_err(|_| "EVENT_SESSION_UNAVAILABLE")?;
    let actual = value["dataRoot"].as_str().ok_or("EVENT_ROOT_MISMATCH")?;
    if std::fs::canonicalize(actual).map_err(|_| "EVENT_ROOT_MISMATCH")? !=
        std::fs::canonicalize(data_root()?).map_err(|_| "EVENT_ROOT_MISMATCH")? {
        return Err("EVENT_ROOT_MISMATCH".into());
    }
    let capture = &value["capture"];
    if capture["state"] != "RUNNING" {return Err("EVENT_SESSION_UNAVAILABLE".into());}
    capture["sessionId"].as_str().map(str::to_owned).ok_or("EVENT_SESSION_UNAVAILABLE".into())
}
