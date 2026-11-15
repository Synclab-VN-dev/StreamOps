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
use std::time::Duration;
const LIMIT: usize = 32 * 1024 * 1024;
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
    if request.headers().get("host").and_then(|h| h.to_str().ok())
        != origin.split_once("://").map(|(_, host)| host)
    {
        return Err(Error::new(403, "HOST_REJECTED"));
    }
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
    let _permit = s
        .relay_requests
        .clone()
        .try_acquire_owned()
        .map_err(|_| Error::new(429, "PLANNER_REQUEST_LIMIT"))?;
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
    let body = to_bytes(request.into_body(), LIMIT)
        .await
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
