//! Native owns the backend HTTP child. Only a random loopback session token crosses the pipe.
use crate::{Config, Result};
use serde_json::Value;
use std::{
    io::{BufRead, BufReader, Read, Write},
    path::Path,
    process::{Child, Command, Stdio},
    sync::mpsc,
    time::Duration,
};

pub struct LocalGateway {
    child: Child,
    recipient: String,
    max_bytes: u64,
    endpoint: String,
    credential: String,
}
impl Drop for LocalGateway {
    fn drop(&mut self) {
        // Reap on every exit, including preflight failure and transport uncertainty.
        self.child.stdin.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
fn frame(receiver: &mpsc::Receiver<Result<Value>>) -> Result<Value> {
    let value = receiver
        .recv_timeout(Duration::from_secs(75))
        .map_err(|_| "LOCAL_GATEWAY_TIMEOUT")??;
    if let Some(code) = value.get("error").and_then(Value::as_str) {
        // The child emits fixed codes only; do not surface arbitrary diagnostic text.
        if code.len() <= 80
            && code
                .bytes()
                .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
        {
            return Err(code.into());
        }
        return Err("LOCAL_GATEWAY_FAILED".into());
    }
    Ok(value)
}
impl LocalGateway {
    pub fn start(python: &Path, root: &Path) -> Result<Self> {
        if !python.is_absolute()
            || !python.is_file()
            || !root.is_absolute()
            || !d4planner_runtime_logging::safe(python)
            || !d4planner_runtime_logging::safe(root)
        {
            return Err("LOCAL_GATEWAY_UNAVAILABLE".into());
        }
        let mut command = Command::new(python);
        command
            .args(["-m", "d4planner.reporting.local", "--data-root"])
            .arg(root)
            .current_dir(root)
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let child = command.spawn().map_err(|_| "LOCAL_GATEWAY_UNAVAILABLE")?;
        let mut owned = Self {
            child,
            recipient: String::new(),
            max_bytes: 0,
            endpoint: String::new(),
            credential: String::new(),
        };
        let stdout = owned.child.stdout.take().ok_or("LOCAL_GATEWAY_FAILED")?;
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            for _ in 0..2 {
                let mut line = String::new();
                let result = reader
                    .by_ref()
                    .take(8193)
                    .read_line(&mut line)
                    .map_err(|_| "LOCAL_GATEWAY_FAILED".to_owned())
                    .and_then(|n| {
                        if n == 0 || n > 8192 {
                            Err("LOCAL_GATEWAY_FAILED".into())
                        } else {
                            serde_json::from_str(&line).map_err(|_| "LOCAL_GATEWAY_FAILED".into())
                        }
                    });
                if sender.send(result).is_err() {
                    break;
                }
            }
        });
        let public = frame(&receiver)?;
        owned.recipient = public["recipient"]
            .as_str()
            .ok_or("INVALID_REPORT_CONFIG")?
            .into();
        owned.max_bytes = public["maxBytes"].as_u64().ok_or("INVALID_REPORT_CONFIG")?;
        Config {
            recipient: owned.recipient.clone(),
            max_bytes: owned.max_bytes,
            gateway: "http://127.0.0.1:1".into(),
        }
        .validate()?;
        owned
            .child
            .stdin
            .as_mut()
            .ok_or("LOCAL_GATEWAY_FAILED")?
            .write_all(b"START\n")
            .map_err(|_| "LOCAL_GATEWAY_FAILED")?;
        let ready = frame(&receiver)?;
        owned.endpoint = ready["gateway"]
            .as_str()
            .ok_or("LOCAL_GATEWAY_FAILED")?
            .into();
        let url = reqwest::Url::parse(&owned.endpoint).map_err(|_| "LOCAL_GATEWAY_FAILED")?;
        if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") {
            return Err("LOCAL_GATEWAY_FAILED".into());
        }
        owned.credential = ready["accessToken"]
            .as_str()
            .ok_or("LOCAL_GATEWAY_FAILED")?
            .into();
        if owned.credential.len() < 32
            || owned.credential.len() > 256
            || owned.credential.chars().any(char::is_whitespace)
        {
            return Err("LOCAL_GATEWAY_FAILED".into());
        }
        owned.config()?;
        Ok(owned)
    }
    pub fn config(&self) -> Result<Config> {
        let config = Config {
            recipient: self.recipient.clone(),
            gateway: self.endpoint.clone(),
            max_bytes: self.max_bytes,
        };
        config.validate()?;
        Ok(config)
    }
    pub fn credential(&self) -> &str {
        &self.credential
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_numeric_loopback_http_with_port_is_accepted() {
        let mut config = Config {
            recipient: age::x25519::Identity::generate().to_public().to_string(),
            gateway: "http://127.0.0.1:12345".into(),
            max_bytes: 1000,
        };
        assert!(config.validate().is_ok());
        for url in [
            "http://localhost:12345",
            "http://192.168.1.8:12345",
            "http://127.0.0.1",
            "http://127.0.0.1:12345/path",
            "http://user@127.0.0.1:12345",
            "http://127.0.0.1:12345/?x=1",
        ] {
            config.gateway = url.into();
            assert!(config.validate().is_err(), "{url}");
        }
    }
}
