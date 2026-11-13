use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeSet,
    net::{Ipv4Addr, SocketAddrV4},
    path::PathBuf,
};

pub const VERSION: &str = "d4planner-hud-web/v1";
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Credential {
    pub subject: String,
    pub sha256: String,
    pub permissions: BTreeSet<String>,
}
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Config {
    pub address: Ipv4Addr,
    pub port: u16,
    pub planner_port: u16,
    pub certificate: Option<PathBuf>,
    pub private_key: Option<PathBuf>,
    pub credentials: Vec<Credential>,
}
impl Config {
    pub fn validate(&self) -> Result<(), Error> {
        let ip = self.address;
        if (!ip.is_loopback() && !ip.is_private())
            || self.port < 1024
            || self.planner_port < 1024
            || self.port == self.planner_port
            || self.certificate.is_some() != self.private_key.is_some()
            || (!ip.is_loopback() && self.certificate.is_none())
            || self.credentials.is_empty()
            || self.credentials.len() > 32
        {
            return Err(Error::bad("WEB_CONFIG_INVALID"));
        }
        let mut subjects = BTreeSet::new();
        let mut hashes = BTreeSet::new();
        for c in &self.credentials {
            if c.subject.is_empty()
                || c.subject.len() > 64
                || !c
                    .subject
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
                || !subjects.insert(&c.subject)
                || !hashes.insert(&c.sha256)
                || c.sha256.len() != 64
                || !c
                    .sha256
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
                || c.permissions
                    .iter()
                    .any(|p| !PERMISSIONS.contains(&p.as_str()))
            {
                return Err(Error::bad("WEB_CONFIG_INVALID"));
            }
        }
        for p in [&self.certificate, &self.private_key].into_iter().flatten() {
            if !p.is_absolute() || !p.is_file() {
                return Err(Error::bad("WEB_TLS_UNAVAILABLE"));
            }
        }
        Ok(())
    }
    pub fn origin(&self, planner: bool) -> String {
        format!(
            "{}://{}:{}",
            if self.certificate.is_some() {
                "https"
            } else {
                "http"
            },
            self.address,
            if planner {
                self.planner_port
            } else {
                self.port
            }
        )
    }
    pub fn socket(&self, planner: bool) -> SocketAddrV4 {
        SocketAddrV4::new(
            self.address,
            if planner {
                self.planner_port
            } else {
                self.port
            },
        )
    }
}
pub const PERMISSIONS: &[&str] = &[
    "hud.read",
    "target.select",
    "runtime.control",
    "planner.open",
    "report.read",
    "report.preview",
    "report.submit",
];
#[derive(Clone)]
pub struct Actor {
    pub subject: String,
    pub permissions: BTreeSet<String>,
}
#[derive(Clone, Copy, Debug)]
pub enum Operation {
    Targets,
    SelectTarget,
    RuntimeStart,
    RuntimeStop,
    RuntimeRestart,
    CaptureStart,
    CaptureStop,
    CaptureRestart,
    PlannerReady,
    ReportPreview,
    ReportSubmit,
    ReportStatus,
    ReportCancel,
}
#[derive(Clone)]
pub struct Bootstrap {
    pub endpoint: String,
    pub credential: String,
    pub origin: String,
}
pub struct Asset {
    pub body: Vec<u8>,
    pub content_type: String,
}
/// Blocking callbacks supplied by Tauri. The library owns no Backend/Rule Kit process.
pub trait Host: Send + Sync + 'static {
    fn read_hud(&self) -> Result<Option<Value>, Error>;
    fn bootstrap(&self) -> Result<Bootstrap, Error>;
    fn runtime(&self) -> Result<Value, Error>;
    fn operation(&self, operation: Operation, params: Value, actor: Actor) -> Result<Value, Error>;
    fn asset(&self, path: &str) -> Option<Asset>;
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Error {
    pub code: String,
    pub state: Option<String>,
    #[serde(skip)]
    pub status: u16,
}
impl Error {
    pub fn new(status: u16, code: &str) -> Self {
        Self {
            status,
            code: code.into(),
            state: None,
        }
    }
    pub fn bad(code: &str) -> Self {
        Self::new(400, code)
    }
    pub fn unavailable() -> Self {
        Self::new(503, "BACKEND_UNAVAILABLE")
    }
}
impl axum::response::IntoResponse for Error {
    fn into_response(self) -> axum::response::Response {
        (
            axum::http::StatusCode::from_u16(self.status)
                .unwrap_or(axum::http::StatusCode::INTERNAL_SERVER_ERROR),
            axum::Json(serde_json::json!({"schemaVersion":VERSION,"error":self})),
        )
            .into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn config() -> Config {
        Config {
            address: Ipv4Addr::LOCALHOST,
            port: 6090,
            planner_port: 6091,
            certificate: None,
            private_key: None,
            credentials: vec![Credential {
                subject: "owner".into(),
                sha256: "a".repeat(64),
                permissions: ["hud.read".into()].into(),
            }],
        }
    }
    #[test]
    fn private_lan_requires_tls_and_public_wildcard_is_never_allowed() {
        let mut c = config();
        assert!(c.validate().is_ok());
        for ip in ["0.0.0.0", "8.8.8.8", "192.168.1.20", "10.0.0.10"] {
            c.address = ip.parse().unwrap();
            assert!(c.validate().is_err());
        }
    }
    #[test]
    fn colliding_ports_duplicate_credentials_and_unknown_scopes_fail_closed() {
        let mut c = config();
        c.planner_port = c.port;
        assert!(c.validate().is_err());
        let mut c = config();
        c.credentials.push(c.credentials[0].clone());
        assert!(c.validate().is_err());
        let mut c = config();
        c.credentials[0].permissions.insert("admin".into());
        assert!(c.validate().is_err());
    }
}
