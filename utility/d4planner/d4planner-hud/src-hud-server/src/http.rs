use crate::{
    auth::Auth,
    model::*,
    operations::{policy, Dispatcher},
};
use axum::{
    extract::{DefaultBodyLimit, Path, Request, State},
    http::{HeaderMap, HeaderValue, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use futures_util::SinkExt;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    sync::{Arc, Mutex},
    time::Duration,
};

#[derive(Clone)]
pub struct HttpState {
    pub(crate) config: Arc<Config>,
    auth: Arc<Mutex<Auth>>,
    pub(crate) dispatcher: Dispatcher,
    host: Arc<dyn Host>,
    feed: Option<crate::Feed>,
    planner: Arc<tokio::sync::Mutex<Option<(std::time::Instant, Value)>>>,
    clients: Arc<tokio::sync::Semaphore>,
    pub(crate) relay_requests: Arc<tokio::sync::Semaphore>,
}
impl HttpState {
    pub fn new(config: Config, host: Arc<dyn Host>) -> Result<Self, Error> {
        config.validate()?;
        Ok(Self {
            auth: Arc::new(Mutex::new(Auth::new(config.credentials.clone()))),
            dispatcher: Dispatcher::new(host.clone(), Duration::from_secs(65)),
            config: Arc::new(config),
            host,
            feed: None,
            planner: Arc::new(tokio::sync::Mutex::new(None)),
            clients: Arc::new(tokio::sync::Semaphore::new(32)),
            relay_requests: Arc::new(tokio::sync::Semaphore::new(32)),
        })
    }
    pub(crate) async fn planner_ready(&self, actor: Actor, refresh: bool) -> Result<Value, Error> {
        let mut current = tokio::time::timeout(Duration::from_secs(65), self.planner.lock())
            .await
            .map_err(|_| Error::new(503, "PLANNER_BUSY"))?;
        if !refresh {
            if let Some((at, value)) = &*current {
                if at.elapsed() < Duration::from_secs(2) {
                    return Ok(value.clone());
                }
            }
        }
        let value = self
            .dispatcher
            .call(Operation::PlannerReady, json!({}), actor)
            .await?;
        crate::relay::upstream(&value)?;
        *current = Some((std::time::Instant::now(), value.clone()));
        Ok(value)
    }
    pub fn with_feed(mut self, feed: crate::Feed) -> Self {
        self.feed = Some(feed);
        self
    }
    pub(crate) fn actor(
        &self,
        headers: &HeaderMap,
        scope: &str,
        mutation: bool,
    ) -> Result<Actor, Error> {
        self.auth
            .lock()
            .map_err(|_| Error::unavailable())?
            .actor(headers, scope, mutation)
    }
}
pub fn router(state: HttpState) -> Router {
    Router::new()
        .route("/api/v1/session", get(session).post(login).delete(logout))
        .route("/api/v1/health", get(health))
        .route("/api/v1/hud/stream", get(stream))
        .route("/api/v1/targets", get(targets))
        .route("/api/v1/planner/open", post(planner_open))
        .route("/api/v1/targets/select", post(select_target))
        .route("/api/v1/runtime/{component}/{action}", post(runtime))
        .route("/api/v1/reports/preview", post(preview))
        .route(
            "/api/v1/reports/{report_id}",
            get(report_status).delete(report_cancel),
        )
        .route("/api/v1/reports/{report_id}/submit", post(submit))
        .fallback(asset)
        .layer(DefaultBodyLimit::max(64 * 1024))
        .layer(middleware::from_fn_with_state(state.clone(), boundary))
        .with_state(state)
}
async fn boundary(State(state): State<HttpState>, request: Request, next: Next) -> Response {
    let origin = state.config.origin(false);
    let expected_host = origin.split_once("://").unwrap().1;
    let headers = request.headers();
    if headers.get("host").and_then(|v| v.to_str().ok()) != Some(expected_host) {
        return Error::new(403, "HOST_REJECTED").into_response();
    }
    // Ports are distinct origins but cookies are shared by host. Reject the Planner
    // origin even for GETs; SameSite alone cannot isolate a captured application.
    if headers
        .get("origin")
        .is_some_and(|v| v.as_bytes() != origin.as_bytes())
    {
        return Error::new(403, "ORIGIN_REJECTED").into_response();
    }
    if !matches!(
        *request.method(),
        axum::http::Method::GET | axum::http::Method::HEAD
    ) && !headers.contains_key("origin")
        && !headers.contains_key("authorization")
    {
        return Error::new(403, "ORIGIN_REQUIRED").into_response();
    }
    if headers
        .get("sec-fetch-site")
        .is_some_and(|v| v == "cross-site" || v == "same-site")
    {
        return Error::new(403, "FETCH_SITE_REJECTED").into_response();
    }
    let mut response = next.run(request).await;
    let h = response.headers_mut();
    h.insert("cache-control", HeaderValue::from_static("no-store"));
    h.insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    h.insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    h.insert(
        "cross-origin-resource-policy",
        HeaderValue::from_static("same-origin"),
    );
    h.insert("content-security-policy",HeaderValue::from_static("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"));
    response
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Login {
    token: String,
}
async fn login(State(s): State<HttpState>, Json(input): Json<Login>) -> Result<Response, Error> {
    let (id, csrf) = s
        .auth
        .lock()
        .map_err(|_| Error::unavailable())?
        .login(&input.token)?;
    let cookie = format!(
        "d4hud_session={id}; Path=/; HttpOnly; SameSite=Strict; Max-Age=3600{}",
        if s.config.certificate.is_some() {
            "; Secure"
        } else {
            ""
        }
    );
    Ok((
        [("set-cookie", cookie)],
        Json(json!({"schemaVersion":VERSION,"csrf":csrf})),
    )
        .into_response())
}
async fn session(State(s): State<HttpState>, headers: HeaderMap) -> Result<Json<Value>, Error> {
    let (actor, csrf) = s
        .auth
        .lock()
        .map_err(|_| Error::unavailable())?
        .session(&headers)?;
    Ok(Json(
        json!({"schemaVersion":VERSION,"subject":actor.subject,"permissions":actor.permissions,"csrf":csrf}),
    ))
}
async fn logout(State(s): State<HttpState>, headers: HeaderMap) -> Result<Response, Error> {
    s.actor(&headers, "hud.read", true)?;
    s.auth
        .lock()
        .map_err(|_| Error::unavailable())?
        .logout(&headers);
    Ok((
        [(
            "set-cookie",
            "d4hud_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
        )],
        StatusCode::NO_CONTENT,
    )
        .into_response())
}
async fn health(State(s): State<HttpState>, headers: HeaderMap) -> Result<Json<Value>, Error> {
    s.actor(&headers, "hud.read", false)?;
    Ok(Json(
        json!({"schemaVersion":VERSION,"status":"READY","backend":s.feed.as_ref().map(|f|f.receiver.borrow()["runtime"]["backend"].clone())}),
    ))
}
async fn call(
    s: HttpState,
    headers: HeaderMap,
    operation: Operation,
    params: Value,
) -> Result<Json<Value>, Error> {
    let (scope, mutation) = policy(operation);
    let actor = s.actor(&headers, scope, mutation)?;
    let result = s.dispatcher.call(operation, params, actor).await;
    if matches!(
        operation,
        Operation::RuntimeStart | Operation::RuntimeStop | Operation::RuntimeRestart
    ) {
        *s.planner.lock().await = None;
    }
    result.map(Json)
}
async fn targets(State(s): State<HttpState>, h: HeaderMap) -> Result<Json<Value>, Error> {
    call(s, h, Operation::Targets, json!({})).await
}
async fn select_target(
    State(s): State<HttpState>,
    h: HeaderMap,
    Json(p): Json<Value>,
) -> Result<Json<Value>, Error> {
    call(s, h, Operation::SelectTarget, p).await
}
async fn preview(
    State(s): State<HttpState>,
    h: HeaderMap,
    Json(p): Json<Value>,
) -> Result<Json<Value>, Error> {
    call(s, h, Operation::ReportPreview, p).await
}
async fn runtime(
    State(s): State<HttpState>,
    h: HeaderMap,
    Path((component, action)): Path<(String, String)>,
) -> Result<Json<Value>, Error> {
    let operation = match (component.as_str(), action.as_str()) {
        ("backend", "start") => Operation::RuntimeStart,
        ("backend", "stop") => Operation::RuntimeStop,
        ("backend", "restart") => Operation::RuntimeRestart,
        ("capture", "start") => Operation::CaptureStart,
        ("capture", "stop") => Operation::CaptureStop,
        ("capture", "restart") => Operation::CaptureRestart,
        _ => return Err(Error::new(404, "ROUTE_NOT_FOUND")),
    };
    call(s, h, operation, json!({})).await
}
fn report_id(id: &str) -> Result<(), Error> {
    if uuid::Uuid::parse_str(id).is_err() {
        return Err(Error::bad("REPORT_ID_INVALID"));
    }
    Ok(())
}
async fn report_status(
    State(s): State<HttpState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Result<Json<Value>, Error> {
    report_id(&id)?;
    call(s, h, Operation::ReportStatus, json!({"reportId":id})).await
}
async fn report_cancel(
    State(s): State<HttpState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Result<Json<Value>, Error> {
    report_id(&id)?;
    call(s, h, Operation::ReportCancel, json!({"reportId":id})).await
}
async fn submit(
    State(s): State<HttpState>,
    h: HeaderMap,
    Path(id): Path<String>,
    Json(mut p): Json<Value>,
) -> Result<Json<Value>, Error> {
    report_id(&id)?;
    let object = p.as_object_mut().ok_or(Error::bad("INVALID_REQUEST"))?;
    if object.contains_key("reportId") {
        return Err(Error::bad("INVALID_REQUEST"));
    }
    object.insert("reportId".into(), json!(id));
    call(s, h, Operation::ReportSubmit, p).await
}
async fn asset(State(s): State<HttpState>, request: Request) -> Result<Response, Error> {
    if request.method() != axum::http::Method::GET {
        return Err(Error::new(405, "METHOD_NOT_ALLOWED"));
    }
    let path = request.uri().path();
    if path.starts_with("/api/") || path.contains("..") || path.contains('%') || path.contains('\\')
    {
        return Err(Error::new(404, "RESOURCE_NOT_FOUND"));
    }
    let asset = s
        .host
        .asset(if path == "/" {
            "index.html"
        } else {
            path.trim_start_matches('/')
        })
        .ok_or(Error::new(404, "RESOURCE_NOT_FOUND"))?;
    Ok(([("content-type", asset.content_type)], asset.body).into_response())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use sha2::{Digest, Sha256};
    use tower::ServiceExt;
    struct Fake;
    impl Host for Fake {
        fn read_hud(&self) -> Result<Option<Value>, Error> {
            Ok(None)
        }
        fn bootstrap(&self) -> Result<Bootstrap, Error> {
            Err(Error::unavailable())
        }
        fn runtime(&self) -> Result<Value, Error> {
            Ok(Value::Null)
        }
        fn operation(&self, _: Operation, _: Value, _: Actor) -> Result<Value, Error> {
            Ok(json!({"accepted":true}))
        }
        fn asset(&self, path: &str) -> Option<Asset> {
            (path == "index.html").then(|| Asset {
                body: b"shared-build".to_vec(),
                content_type: "text/html".into(),
            })
        }
    }
    fn app() -> Router {
        let config = Config {
            address: "127.0.0.1".parse().unwrap(),
            port: 6090,
            planner_port: 6091,
            certificate: None,
            private_key: None,
            credentials: vec![Credential {
                subject: "owner".into(),
                sha256: format!("{:x}", Sha256::digest(b"01234567890123456789012345678901")),
                permissions: ["hud.read".into(), "runtime.control".into()].into(),
            }],
        };
        router(HttpState::new(config, Arc::new(Fake)).unwrap())
    }
    fn request(path: &str) -> axum::http::request::Builder {
        Request::builder()
            .uri(path)
            .header("host", "127.0.0.1:6090")
    }
    #[tokio::test]
    async fn unknown_or_unauthenticated_api_never_falls_back_to_html() {
        let app = app();
        for (path, status) in [("/api/v1/health", 401), ("/api/v1/snapshot", 404)] {
            assert_eq!(
                app.clone()
                    .oneshot(request(path).body(Body::empty()).unwrap())
                    .await
                    .unwrap()
                    .status()
                    .as_u16(),
                status
            );
        }
    }
    #[tokio::test]
    async fn rejects_planner_origin_and_dns_rebinding() {
        let app = app();
        let cross = request("/")
            .header("origin", "http://127.0.0.1:6091")
            .body(Body::empty())
            .unwrap();
        assert_eq!(
            app.clone().oneshot(cross).await.unwrap().status(),
            StatusCode::FORBIDDEN
        );
        let rebind = Request::builder()
            .uri("/")
            .header("host", "attacker.example:6090")
            .body(Body::empty())
            .unwrap();
        assert_eq!(
            app.oneshot(rebind).await.unwrap().status(),
            StatusCode::FORBIDDEN
        );
    }
    #[tokio::test]
    async fn login_and_native_control_require_session_and_csrf() {
        let app = app();
        let login = request("/api/v1/session")
            .method("POST")
            .header("origin", "http://127.0.0.1:6090")
            .header("content-type", "application/json")
            .body(Body::from(
                r#"{"token":"01234567890123456789012345678901"}"#,
            ))
            .unwrap();
        let response = app.clone().oneshot(login).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let cookie = response.headers()["set-cookie"]
            .to_str()
            .unwrap()
            .split(';')
            .next()
            .unwrap()
            .to_owned();
        let body = axum::body::to_bytes(response.into_body(), 4096)
            .await
            .unwrap();
        let value: Value = serde_json::from_slice(&body).unwrap();
        let command = || {
            request("/api/v1/runtime/backend/start")
                .method("POST")
                .header("origin", "http://127.0.0.1:6090")
                .header("cookie", &cookie)
        };
        assert_eq!(
            app.clone()
                .oneshot(command().body(Body::empty()).unwrap())
                .await
                .unwrap()
                .status(),
            StatusCode::FORBIDDEN
        );
        assert_eq!(
            app.oneshot(
                command()
                    .header("x-hud-csrf", value["csrf"].as_str().unwrap())
                    .body(Body::empty())
                    .unwrap()
            )
            .await
            .unwrap()
            .status(),
            StatusCode::OK
        );
    }
}

async fn stream(
    State(s): State<HttpState>,
    headers: HeaderMap,
    upgrade: axum::extract::ws::WebSocketUpgrade,
) -> Result<Response, Error> {
    // Browser WebSockets always send Origin. Do not allow cross-origin or opaque
    // origins to reuse the host-wide session cookie.
    if headers.get("origin").and_then(|v| v.to_str().ok()) != Some(s.config.origin(false).as_str())
    {
        return Err(Error::new(403, "ORIGIN_REQUIRED"));
    }
    s.actor(&headers, "hud.read", false)?;
    let permit = s
        .clients
        .clone()
        .try_acquire_owned()
        .map_err(|_| Error::new(429, "CLIENT_LIMIT"))?;
    let mut feed = s.feed.clone().ok_or(Error::unavailable())?.receiver;
    Ok(upgrade.max_message_size(4096).max_frame_size(4096).on_upgrade(move|mut socket|async move{
        let _permit=permit;
        let mut heartbeat=tokio::time::interval(Duration::from_secs(20));
        loop {
            let value=feed.borrow_and_update().clone();
            if !matches!(tokio::time::timeout(Duration::from_secs(5),socket.send(axum::extract::ws::Message::Text(value.to_string().into()))).await,Ok(Ok(()))){break;}
            tokio::select!{
                changed=feed.changed()=>{if changed.is_err(){break;}}
                _=heartbeat.tick()=>{if s.actor(&headers,"hud.read",false).is_err(){break;}}
                message=socket.recv()=>{match message {Some(Ok(axum::extract::ws::Message::Pong(_)))=>{},_=>break}}
            }
        }
        let _=socket.close().await;
    }).into_response())
}

async fn planner_open(State(s): State<HttpState>, h: HeaderMap) -> Result<Json<Value>, Error> {
    let actor = s.actor(&h, "planner.open", true)?;
    let mut result = s.planner_ready(actor, true).await?;
    crate::relay::upstream(&result)?;
    result["url"] = json!(format!("{}/", s.config.origin(true)));
    Ok(Json(result))
}
