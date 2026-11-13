//! Explicit synthetic host for HTTP/browser tests, never linked into production.
use d4planner_hud_server::{model::*, RunningServer};
use d4planner_report_issue::{coordinator::Coordinator, Description, Selection};
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::{
    path::PathBuf,
    sync::{Arc, Mutex},
};
struct Fixture {
    dist: PathBuf,
    data: PathBuf,
    hud: Value,
    endpoint: String,
    state: Mutex<String>,
    reports: Mutex<Coordinator>,
    planner: Option<Value>,
}
impl Host for Fixture {
    fn read_hud(&self) -> Result<Option<Value>, Error> {
        Ok(Some(
            json!({"schemaVersion":"d4planner-hud-db/v1","dbId":"fixture-db","epoch":"fixture-epoch","hudRevision":self.hud["hudRevision"],"hud":self.hud}),
        ))
    }
    fn bootstrap(&self) -> Result<Bootstrap, Error> {
        if *self.state.lock().unwrap() != "READY" {
            return Err(Error::unavailable());
        }
        Ok(Bootstrap {
            endpoint: self.endpoint.clone(),
            credential: "synthetic-fixture-credential-not-production".into(),
            origin: "tauri://localhost".into(),
        })
    }
    fn runtime(&self) -> Result<Value, Error> {
        Ok(
            json!({"backend":{"state":*self.state.lock().unwrap(),"ready":{"childInstanceId":self.hud["backend"]["runtimeInstanceId"],"generation":self.hud["backend"]["generation"]}},"runtime":{"pid":std::process::id(),"uptimeSeconds":1,"dataRoot":"Private on host","webSocket":null,"capture":{"state":"STOPPED","pid":null,"manualPause":false,"dependencies":{},"speechEvents":0,"mode":"fixture","detail":"Synthetic test host","controllerProfile":"fixture"}}}),
        )
    }
    fn asset(&self, path: &str) -> Option<Asset> {
        let p = self.dist.join(path);
        let body = std::fs::read(&p).ok()?;
        let content_type = match p.extension()?.to_str()? {
            "html" => "text/html",
            "js" => "text/javascript",
            "css" => "text/css",
            "svg" => "image/svg+xml",
            _ => "application/octet-stream",
        };
        Some(Asset {
            body,
            content_type: content_type.into(),
        })
    }
    fn operation(&self, op: Operation, p: Value, actor: Actor) -> Result<Value, Error> {
        let result: Result<Value, String> = match op {
            Operation::RuntimeStart | Operation::RuntimeRestart => {
                *self.state.lock().unwrap() = "READY".into();
                return self.runtime();
            }
            Operation::RuntimeStop => {
                *self.state.lock().unwrap() = "STOPPED".into();
                return self.runtime();
            }
            Operation::CaptureStart | Operation::CaptureStop | Operation::CaptureRestart => {
                Ok(Value::Null)
            }
            Operation::Targets => Ok(json!({"listRevision":1,"targets":[]})),
            Operation::SelectTarget => Err("TARGET_NOT_FOUND".into()),
            Operation::PlannerReady => self.planner.clone().ok_or("PLANNER_UNAVAILABLE".into()),
            Operation::ReportPreview => {
                let selection: Selection = serde_json::from_value(p["selection"].clone())
                    .map_err(|_| Error::bad("INVALID_REQUEST"))?;
                self.reports.lock().unwrap().collect(
                    &self.data,
                    "00000000-0000-4000-8000-000000000201",
                    &actor.subject,
                    selection,
                    |_| Err("RAW_EVENT_SOURCE_NOT_BOUND".into()),
                )
            }
            Operation::ReportStatus => self.reports.lock().unwrap().status(
                &self.data,
                &actor.subject,
                p["reportId"].as_str().unwrap_or(""),
            ),
            Operation::ReportCancel => self
                .reports
                .lock()
                .unwrap()
                .cancel(&self.data, &actor.subject, p["reportId"].as_str())
                .map(|_| Value::Null),
            Operation::ReportSubmit => {
                let d: Description = serde_json::from_value(p["description"].clone())
                    .map_err(|_| Error::bad("INVALID_REQUEST"))?;
                return self
                    .reports
                    .lock()
                    .unwrap()
                    .submit(
                        &self.data,
                        &actor.subject,
                        p["reportId"].as_str().unwrap_or(""),
                        d,
                        p["consent"] == true,
                        |r, d, c| {
                            r.attempt(
                                Err("REPORT_NOT_CONFIGURED".into()),
                                Err("AUTHENTICATION_REQUIRED".into()),
                                d,
                                c,
                            )
                        },
                    )
                    .map_err(|e| Error {
                        code: e.code,
                        state: Some(e.state.into()),
                        status: 400,
                    });
            }
        };
        result.map_err(|code| Error::new(503, &code))
    }
}
#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    assert_eq!(args.len(), 5, "config dist hud data arguments required");
    let config: Config = serde_json::from_slice(&std::fs::read(&args[1]).unwrap()).unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let endpoint = format!("ws://{}", listener.local_addr().unwrap());
    let notification = tokio::spawn(async move {
        loop {
            let (tcp, _) = listener.accept().await.unwrap();
            tokio::spawn(async move {
                let mut s = tokio_tungstenite::accept_async(tcp).await.unwrap();
                let m = s.next().await.unwrap().unwrap();
                let m: Value = serde_json::from_str(m.to_text().unwrap()).unwrap();
                let accepted = json!({"protocolVersion":"d4planner-notify/v1","type":"hello.accepted","correlationId":m["messageId"]});
                s.send(tokio_tungstenite::tungstenite::Message::Text(
                    accepted.to_string().into(),
                ))
                .await
                .unwrap();
                while s.next().await.is_some() {}
            });
        }
    });
    let fixture = Arc::new(Fixture {
        dist: args[2].clone().into(),
        data: args[4].clone().into(),
        hud: serde_json::from_slice(&std::fs::read(&args[3]).unwrap()).unwrap(),
        endpoint,
        state: Mutex::new("READY".into()),
        reports: Mutex::new(Coordinator::new()),
        planner: std::env::var("D4_TEST_PLANNER_READY")
            .ok()
            .map(|s| serde_json::from_str(&s).unwrap()),
    });
    let server = RunningServer::start(config, fixture).await.unwrap();
    println!(
        "{}",
        json!({"url":server.url,"pid":std::process::id(),"classification":"SYNTHETIC_HOST_HTTP"})
    );
    tokio::task::spawn_blocking(|| {
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).unwrap();
    })
    .await
    .unwrap();
    server.shutdown().await.unwrap();
    notification.abort();
    println!("STOPPED");
}
