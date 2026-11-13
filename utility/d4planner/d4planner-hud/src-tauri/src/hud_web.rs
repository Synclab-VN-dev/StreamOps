//! Typed callbacks into existing native ownership, never an IPC proxy.
use super::*;
use d4planner_hud_server::{
    model::{Actor, Asset, Bootstrap, Config, Error, Host, Operation},
    RunningServer,
};
use serde_json::{json, Value};

pub struct WebState(pub Mutex<Option<RunningServer>>);
struct NativeHost {
    app: tauri::AppHandle,
}
fn safe_error(code: String) -> Error {
    let safe = if code.len() <= 80
        && code
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
    {
        code
    } else {
        "OPERATION_FAILED".into()
    };
    Error::new(if safe.contains("BUSY") { 409 } else { 503 }, &safe)
}
impl Host for NativeHost {
    fn read_hud(&self) -> Result<Option<Value>, Error> {
        tauri::async_runtime::block_on(read_hud_database()).map_err(safe_error)
    }
    fn bootstrap(&self) -> Result<Bootstrap, Error> {
        let b = get_hud_ws_bootstrap(self.app.state()).map_err(safe_error)?;
        Ok(Bootstrap {
            endpoint: b.endpoint,
            credential: b.credential,
            origin: b.origin,
        })
    }
    fn runtime(&self) -> Result<Value, Error> {
        let backend = get_backend_status(self.app.state()).map_err(safe_error)?;
        let ready = backend
            .ready
            .as_ref()
            .map(|r| json!({"childInstanceId":r.child_instance_id,"generation":r.generation}));
        let runtime = if backend.state == ProcessState::Ready {
            tauri::async_runtime::block_on(backend_command(
                self.app.state(),
                "runtime.status".into(),
                json!({}),
            ))
            .ok()
            .map(|mut v| {
                v["dataRoot"] = json!("Private on host");
                v["webSocket"] = Value::Null;
                if let Some(capture) = v.get_mut("capture").and_then(Value::as_object_mut) {
                    capture.insert("dataRootReceipt".into(), json!("PRIVATE"));
                }
                v
            })
        } else {
            None
        };
        Ok(json!({"backend":{"state":backend.state,"ready":ready},"runtime":runtime}))
    }
    fn asset(&self, path: &str) -> Option<Asset> {
        let asset = self.app.asset_resolver().get(path.to_owned())?;
        Some(Asset {
            body: asset.bytes,
            content_type: asset.mime_type,
        })
    }
    fn operation(&self, operation: Operation, params: Value, actor: Actor) -> Result<Value, Error> {
        let owner = format!("web:{}", actor.subject);
        let result: Result<Value, String> = match operation {
            Operation::Targets => tauri::async_runtime::block_on(backend_command(
                self.app.state(),
                "target.list".into(),
                json!({}),
            )),
            Operation::SelectTarget => tauri::async_runtime::block_on(backend_command(
                self.app.state(),
                "target.select".into(),
                params,
            )),
            Operation::RuntimeStart => {
                tauri::async_runtime::block_on(start_backend(self.app.state()))
                    .and_then(|_| self.runtime().map_err(|e| e.code))
            }
            Operation::RuntimeStop => {
                tauri::async_runtime::block_on(stop_backend(self.app.state()))
                    .and_then(|_| self.runtime().map_err(|e| e.code))
            }
            Operation::RuntimeRestart => {
                tauri::async_runtime::block_on(restart_backend(self.app.state()))
                    .and_then(|_| self.runtime().map_err(|e| e.code))
            }
            Operation::CaptureStart | Operation::CaptureStop | Operation::CaptureRestart => {
                let method = match operation {
                    Operation::CaptureStart => "capture.start",
                    Operation::CaptureStop => "capture.stop",
                    _ => "capture.restart",
                };
                tauri::async_runtime::block_on(backend_command(
                    self.app.state(),
                    method.into(),
                    json!({}),
                ))
                .map(|_| Value::Null)
            }
            Operation::PlannerReady => {
                let state = self.app.state::<BackendState>();
                let wrapper = state
                    .0
                    .lock()
                    .map_err(|_| Error::unavailable())?
                    .clone()
                    .ok_or(Error::unavailable())?;
                let ready = planner::ensure_ready(
                    &PLANNER_OPEN_PENDING,
                    planner::configured_port().map_err(safe_error)?,
                    || {
                        wrapper.request(
                            "planner.ensureReady",
                            json!({}),
                            backend_process::PLANNER_CONTROL_TIMEOUT,
                        )
                    },
                )
                .map_err(safe_error)?;
                serde_json::to_value(ready).map_err(|_| "PLANNER_HEALTH_FAILED".into())
            }
            Operation::ReportPreview => {
                #[derive(serde::Deserialize)]
                #[serde(deny_unknown_fields)]
                struct Preview {
                    selection: d4planner_report_issue::Selection,
                }
                let p: Preview =
                    serde_json::from_value(params).map_err(|_| Error::bad("INVALID_REQUEST"))?;
                issue_report::collect(&owner, p.selection)
            }
            Operation::ReportStatus | Operation::ReportCancel => {
                let id = params
                    .get("reportId")
                    .and_then(Value::as_str)
                    .ok_or(Error::bad("INVALID_REQUEST"))?;
                if matches!(operation, Operation::ReportStatus) {
                    issue_report::status(&owner, id)
                } else {
                    issue_report::cancel(&owner, Some(id)).map(|_| Value::Null)
                }
            }
            Operation::ReportSubmit => {
                #[derive(serde::Deserialize)]
                #[serde(rename_all = "camelCase", deny_unknown_fields)]
                struct Submit {
                    report_id: String,
                    description: d4planner_report_issue::Description,
                    consent: bool,
                }
                let p: Submit =
                    serde_json::from_value(params).map_err(|_| Error::bad("INVALID_REQUEST"))?;
                return issue_report::submit(&owner, &p.report_id, p.description, p.consent)
                    .map_err(|failure| {
                        let mut error = safe_error(failure.code);
                        error.state = Some(failure.state.into());
                        error
                    });
            }
        };
        result.map_err(safe_error)
    }
}
pub fn start(app: &tauri::AppHandle) -> Result<(), String> {
    let root = match env::var("D4PLANNER_DATA_ROOT") {
        Ok(p) => PathBuf::from(p),
        Err(_) => return Ok(()),
    };
    let path = root.join("private").join("hud-web-config.json");
    if !path.exists() {
        return Ok(());
    }
    if !root.is_absolute()
        || !d4planner_runtime_logging::safe(&path)
        || fs::metadata(&path).map_err(|_| "WEB_CONFIG_INVALID")?.len() > 65536
    {
        return Err("WEB_CONFIG_INVALID".into());
    }
    let config: Config = serde_json::from_slice(&fs::read(path).map_err(|_| "WEB_CONFIG_INVALID")?)
        .map_err(|_| "WEB_CONFIG_INVALID")?;
    let host = Arc::new(NativeHost { app: app.clone() });
    let server =
        tauri::async_runtime::block_on(RunningServer::start(config, host)).map_err(|e| e.code)?;
    *app.state::<WebState>()
        .0
        .lock()
        .map_err(|_| "WEB_STATE_FAILED")? = Some(server);
    Ok(())
}
pub fn stop(app: &tauri::AppHandle) {
    let server = app
        .state::<WebState>()
        .0
        .lock()
        .ok()
        .and_then(|mut slot| slot.take());
    if let Some(server) = server {
        if tauri::async_runtime::block_on(server.shutdown()).is_err() {
            runtime_event("ERROR", "native", "ERROR");
        }
    }
}
