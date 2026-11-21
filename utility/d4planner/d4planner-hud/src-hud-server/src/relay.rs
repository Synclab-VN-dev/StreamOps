//! Authenticated transport to the Rule Kit-owned Planner. No snapshot replay,
//! compatibility decision, process launch or network fallback belongs here.
use crate::{http::HttpState, model::*};
use axum::{
    body::{to_bytes, Body},
    extract::{Request, State},
    http::HeaderValue,
    response::{IntoResponse, Response},
    Router,
};
use futures_util::StreamExt;
use serde_json::Value;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};
const LIMIT: usize = 32 * 1024 * 1024;
/// Bound both upstream work and waiting requests. A module-preload burst must
/// wait for capacity rather than permanently failing a browser's module graph.
pub(crate) struct Admission {
    active: Arc<Semaphore>,
    waiting: Arc<Semaphore>,
    timeout: Duration,
}
impl Default for Admission {
    fn default() -> Self {
        Self {
            active: Arc::new(Semaphore::new(32)),
            waiting: Arc::new(Semaphore::new(256)),
            timeout: Duration::from_secs(20),
        }
    }
}
impl Admission {
    async fn acquire(&self) -> Result<OwnedSemaphorePermit, Error> {
        if let Ok(permit) = self.active.clone().try_acquire_owned() {
            return Ok(permit);
        }
        let _waiting = self
            .waiting
            .clone()
            .try_acquire_owned()
            .map_err(|_| Error::new(429, "PLANNER_REQUEST_LIMIT"))?;
        // Dropping this future (including client disconnect) releases the queue
        // slot. The returned permit remains held through response buffering.
        tokio::time::timeout(self.timeout, self.active.clone().acquire_owned())
            .await
            .map_err(|_| Error::new(503, "PLANNER_BUSY"))?
            .map_err(|_| Error::unavailable())
    }
}
pub(crate) fn upstream(ready: &Value) -> Result<String, Error> {
    let url = ready["url"].as_str().ok_or(Error::unavailable())?;
    let parsed = reqwest::Url::parse(url).map_err(|_| Error::unavailable())?;
    if ready["schemaVersion"] != "d4planner-local-planner/v1"
        || ready["status"] != "READY"
        || parsed.scheme() != "http"
        || parsed.host_str() != Some("127.0.0.1")
        || parsed.port().is_none()
        || parsed.path() != "/"
        || parsed.query().is_some()
        || parsed.fragment().is_some()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
    {
        return Err(Error::new(503, "PLANNER_HEALTH_FAILED"));
    }
    Ok(url.trim_end_matches('/').to_owned())
}
pub fn router(state: HttpState) -> Router {
    Router::new().fallback(relay).with_state(state)
}
async fn relay(State(s): State<HttpState>, request: Request) -> Result<Response, Error> {
    let origin = s.config.origin(true);
    crate::authority::validate(&request, &origin)?;
    let mutation = !matches!(request.method().as_str(), "GET" | "HEAD");
    if request
        .headers()
        .get("origin")
        .is_some_and(|h| h.as_bytes() != origin.as_bytes())
        || (mutation && !request.headers().contains_key("origin"))
    {
        return Err(Error::new(403, "ORIGIN_REJECTED"));
    }
    if request
        .headers()
        .get("sec-fetch-site")
        .is_some_and(|h| h == "cross-site")
    {
        return Err(Error::new(403, "FETCH_SITE_REJECTED"));
    }
    let actor = s.actor(request.headers(), "planner.open", false)?;
    let path = request
        .uri()
        .path_and_query()
        .map(|v| v.as_str())
        .unwrap_or("/");
    if path.starts_with("/__local/health")
        || path.starts_with("/api/v1/")
        || !matches!(request.method().as_str(), "GET" | "HEAD" | "POST")
    {
        return Err(Error::new(403, "PLANNER_ROUTE_REJECTED"));
    }
    let _permit = s.relay_requests.acquire().await?;
    // Ask the existing owner to verify readiness. Never infer ownership from a
    // previously opened port or an arbitrary HTTP 200 response.
    let ready = s.planner_ready(actor, path == "/").await?;
    let base = upstream(&ready)?;
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(20))
        .build()
        .map_err(|_| Error::unavailable())?;
    let mut forward = client.request(request.method().clone(), format!("{base}{path}"));
    for name in ["content-type", "x-local-snapshot"] {
        if let Some(value) = request.headers().get(name) {
            forward = forward.header(name, value);
        }
    }
    if mutation {
        forward = forward.header("origin", &base);
    }
    let body = tokio::time::timeout(
        Duration::from_secs(20),
        to_bytes(request.into_body(), LIMIT),
    )
    .await
    .map_err(|_| Error::new(408, "REQUEST_TIMEOUT"))?
    .map_err(|_| Error::new(413, "REQUEST_TOO_LARGE"))?;
    let response = forward
        .body(body)
        .send()
        .await
        .map_err(|_| Error::new(503, "PLANNER_UNAVAILABLE"))?;
    let status = response.status();
    let headers = response.headers().clone();
    let mut bytes = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| Error::unavailable())?;
        if bytes.len() + chunk.len() > LIMIT {
            return Err(Error::new(502, "PLANNER_RESOURCE_TOO_LARGE"));
        }
        bytes.extend_from_slice(&chunk);
    }
    let content_type = headers
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("application/octet-stream");
    if ["text/html", "text/css", "javascript"]
        .iter()
        .any(|t| content_type.contains(t))
    {
        bytes = String::from_utf8(bytes)
            .map_err(|_| Error::new(502, "PLANNER_RESOURCE_INVALID"))?
            .replace(&base, &origin)
            .into_bytes();
    }
    let mut result = (status, Body::from(bytes)).into_response();
    for name in [
        "content-type",
        "content-security-policy",
        "permissions-policy",
        "content-disposition",
        "x-content-type-options",
        "referrer-policy",
        "x-dns-prefetch-control",
    ] {
        if let Some(value) = headers.get(name) {
            result.headers_mut().insert(name, value.clone());
        }
    }
    if let Some(location) = headers.get("location") {
        let location = location
            .to_str()
            .map_err(|_| Error::new(502, "PLANNER_REDIRECT_REJECTED"))?;
        let parsed = reqwest::Url::parse(&base)
            .unwrap()
            .join(location)
            .map_err(|_| Error::new(502, "PLANNER_REDIRECT_REJECTED"))?;
        if parsed.origin().ascii_serialization() != base {
            return Err(Error::new(502, "PLANNER_REDIRECT_REJECTED"));
        }
        result.headers_mut().insert(
            "location",
            HeaderValue::from_str(&parsed.as_str().replacen(&base, &origin, 1))
                .map_err(|_| Error::unavailable())?,
        );
    }
    result
        .headers_mut()
        .insert("cache-control", HeaderValue::from_static("no-store"));
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    };
    use tower::ServiceExt;

    #[tokio::test]
    async fn overload_timeout_and_cancellation_release_capacity() {
        let mut gate = Arc::new(Admission {
            active: Arc::new(Semaphore::new(1)),
            waiting: Arc::new(Semaphore::new(1)),
            timeout: Duration::from_secs(10),
        });
        let active = gate.acquire().await.unwrap();
        let queued = tokio::spawn({
            let gate = gate.clone();
            async move { gate.acquire().await }
        });
        tokio::time::timeout(Duration::from_secs(1), async {
            while gate.waiting.available_permits() != 0 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(
            gate.acquire().await.err().unwrap().code,
            "PLANNER_REQUEST_LIMIT"
        );
        queued.abort();
        let _ = queued.await;
        assert_eq!(gate.waiting.available_permits(), 1);
        Arc::get_mut(&mut gate).unwrap().timeout = Duration::from_millis(20);
        assert_eq!(gate.acquire().await.err().unwrap().code, "PLANNER_BUSY");
        assert_eq!(gate.waiting.available_permits(), 1);
        drop(active);
        let recovered = gate.acquire().await.unwrap();
        drop(recovered);
        assert_eq!(gate.active.available_permits(), 1);
    }

    struct Planner(String);
    impl Host for Planner {
        fn read_hud(&self) -> Result<Option<Value>, Error> {
            Ok(None)
        }
        fn bootstrap(&self) -> Result<Bootstrap, Error> {
            Err(Error::unavailable())
        }
        fn runtime(&self) -> Result<Value, Error> {
            Ok(Value::Null)
        }
        fn asset(&self, _: &str) -> Option<Asset> {
            None
        }
        fn operation(&self, op: Operation, _: Value, _: Actor) -> Result<Value, Error> {
            assert!(matches!(op, Operation::PlannerReady));
            Ok(
                serde_json::json!({"schemaVersion":"d4planner-local-planner/v1","status":"READY","url":self.0}),
            )
        }
    }
    #[tokio::test]
    async fn module_burst_waits_instead_of_dropping_valid_assets() {
        let entered = Arc::new(AtomicUsize::new(0));
        let release = Arc::new(tokio::sync::Semaphore::new(0));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let upstream = Router::new().fallback(axum::routing::get({
            let entered = entered.clone();
            let release = release.clone();
            move |headers: axum::http::HeaderMap| {
                let entered = entered.clone();
                let release = release.clone();
                async move {
                    assert!(!headers.contains_key("authorization"));
                    assert!(!headers.contains_key("cookie"));
                    entered.fetch_add(1, Ordering::SeqCst);
                    release.acquire().await.unwrap().forget();
                    (
                        [("content-type", "text/javascript")],
                        "export const loaded = true;",
                    )
                }
            }
        }));
        let server = tokio::spawn(async move { axum::serve(listener, upstream).await.unwrap() });
        let state = HttpState::new(
            Config {
                address: "127.0.0.1".parse().unwrap(),
                port: 6090,
                planner_port: 6091,
                certificate: None,
                private_key: None,
                credentials: vec![Credential {
                    subject: "fixture".into(),
                    sha256: format!(
                        "{:x}",
                        Sha256::digest(b"synthetic-relay-burst-test-token-224")
                    ),
                    permissions: ["planner.open".into()].into(),
                }],
            },
            Arc::new(Planner(format!("http://{address}/"))),
        )
        .unwrap();
        let app = router(state);
        let mut jobs = Vec::new();
        for i in 0..128 {
            let app = app.clone();
            jobs.push(tokio::spawn(async move {
                app.oneshot(
                    Request::builder()
                        .version(axum::http::Version::HTTP_2)
                        .uri(format!("http://127.0.0.1:6091/assets/module-{i}.js"))
                        .header(
                            "authorization",
                            "Bearer synthetic-relay-burst-test-token-224",
                        )
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap()
            }));
        }
        tokio::time::timeout(Duration::from_secs(5), async {
            while entered.load(Ordering::SeqCst) < 32 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        tokio::time::sleep(Duration::from_millis(50)).await;
        assert_eq!(
            entered.load(Ordering::SeqCst),
            32,
            "Active upstream work stays bounded"
        );
        // Saturation must not defer auth/route rejection or send it upstream.
        for (path, authenticated, status) in [("/", false, 401), ("/api/v1/health", true, 403)] {
            let mut request = Request::builder()
                .version(axum::http::Version::HTTP_2)
                .uri(format!("http://127.0.0.1:6091{path}"));
            if authenticated {
                request = request.header(
                    "authorization",
                    "Bearer synthetic-relay-burst-test-token-224",
                );
            }
            let response = tokio::time::timeout(
                Duration::from_secs(1),
                app.clone().oneshot(request.body(Body::empty()).unwrap()),
            )
            .await
            .unwrap()
            .unwrap();
            assert_eq!(response.status().as_u16(), status);
        }
        let early = jobs.iter().filter(|job| job.is_finished()).count();
        release.add_permits(128);
        let mut statuses = Vec::new();
        for job in jobs {
            statuses.push(job.await.unwrap().status().as_u16());
        }
        server.abort();
        assert_eq!(
            early, 0,
            "Queued assets must not be rejected while upstream is busy: {statuses:?}"
        );
        assert!(statuses.iter().all(|&status| status == 200), "{statuses:?}");
    }
    #[test]
    fn relay_never_accepts_arbitrary_upstream_or_unready_result() {
        for url in [
            "https://maxroll.gg/",
            "http://localhost:6085/",
            "http://127.0.0.1:6085/other",
            "http://127.0.0.1:6085/?token=x",
            "http://evil@127.0.0.1:6085/",
            "file:///private",
        ] {
            assert!(upstream(&serde_json::json!({"schemaVersion":"d4planner-local-planner/v1","status":"READY","url":url})).is_err());
        }
        assert!(upstream(&serde_json::json!({"schemaVersion":"d4planner-local-planner/v1","status":"FAILED","url":"http://127.0.0.1:6085/"})).is_err());
        assert_eq!(upstream(&serde_json::json!({"schemaVersion":"d4planner-local-planner/v1","status":"READY","url":"http://127.0.0.1:6085/"})).unwrap(),"http://127.0.0.1:6085");
    }
}
