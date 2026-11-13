//! Native control/browser boundary. React never supplies a URL or process command.
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Ready {
    schema_version: String,
    status: String,
    pub url: String,
    snapshot_id: String,
    manifest_sha256: String,
    reused: bool,
}

pub fn configured_port() -> Result<u16, String> {
    let value = std::env::var("D4_RULEKIT_PLANNER_PORT").unwrap_or_else(|_| "6085".into());
    value.parse::<u16>().ok().filter(|p| *p >= 1024).ok_or("PLANNER_UNAVAILABLE".into())
}

pub fn safe_error(error: &str) -> String {
    match error {
        "PLANNER_SNAPSHOT_UNAVAILABLE" | "PLANNER_SNAPSHOT_UNTRUSTED" |
        "PLANNER_START_FAILED" | "PLANNER_HEALTH_FAILED" | "PLANNER_PORT_CONFLICT" |
        "PLANNER_BUSY" | "PLANNER_UNAVAILABLE" | "PLANNER_RELEASE_NOT_FOUND" | "PLANNER_RELEASE_ACCESS_DENIED" | "PLANNER_DOWNLOAD_FAILED" | "PLANNER_RELEASE_UNTRUSTED" | "PLANNER_DECRYPTION_KEY_REQUIRED" | "PLANNER_DECRYPTION_FAILED" | "PLANNER_RELEASE_ENUMERATION_LIMIT" => error.into(),
        "CONTROL_TIMEOUT" => "PLANNER_HEALTH_FAILED".into(),
        "CONTROL_QUEUE_FULL" => "PLANNER_BUSY".into(),
        _ => "PLANNER_UNAVAILABLE".into(),
    }
}

pub fn open(
    pending: &AtomicBool, port: u16,
    control: impl FnOnce() -> Result<serde_json::Value, String>,
    browser: impl FnOnce(&str) -> Result<(), String>,
) -> Result<Ready, String> {
    let ready=ensure_ready(pending,port,control)?;
    browser(&ready.url).map_err(|_|"PLANNER_UNAVAILABLE")?;
    Ok(ready)
}
pub fn ensure_ready(
    pending: &AtomicBool, port:u16,
    control:impl FnOnce()->Result<serde_json::Value,String>,
)->Result<Ready,String>{
    if pending.swap(true, Ordering::AcqRel) { return Err("PLANNER_BUSY".into()); }
    struct Guard<'a>(&'a AtomicBool);
    impl Drop for Guard<'_> { fn drop(&mut self) { self.0.store(false, Ordering::Release); } }
    let _guard = Guard(pending);
    let result = control().map_err(|e| safe_error(&e))?;
    let ready: Ready = serde_json::from_value(result).map_err(|_| "PLANNER_HEALTH_FAILED")?;
    if port < 1024 || ready.schema_version != "d4planner-local-planner/v1" || ready.status != "READY" ||
        ready.url != format!("http://127.0.0.1:{port}/") || ready.snapshot_id.is_empty() || ready.snapshot_id.len() > 160 ||
        ready.manifest_sha256.len() != 64 || !ready.manifest_sha256.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err("PLANNER_HEALTH_FAILED".into());
    }
    Ok(ready)
}

#[cfg(target_os = "windows")]
pub fn system_browser(url: &str) -> Result<(), String> {
    // ShellExecute receives the validated URL as a file argument, never a shell command.
    #[link(name = "shell32")]
    unsafe extern "system" { fn ShellExecuteW(hwnd: *mut std::ffi::c_void, operation: *const u16,
        file: *const u16, parameters: *const u16, directory: *const u16, show: i32) -> isize; }
    let operation: Vec<u16> = "open\0".encode_utf16().collect();
    let file: Vec<u16> = url.encode_utf16().chain(Some(0)).collect();
    let result = unsafe { ShellExecuteW(std::ptr::null_mut(), operation.as_ptr(), file.as_ptr(),
        std::ptr::null(), std::ptr::null(), 1) };
    if result > 32 { Ok(()) } else { Err("PLANNER_UNAVAILABLE".into()) }
}

#[cfg(not(target_os = "windows"))]
pub fn system_browser(_url: &str) -> Result<(), String> { Err("PLANNER_UNAVAILABLE".into()) }

#[cfg(test)]
mod tests {
    use super::*;
    fn ready(url: &str) -> serde_json::Value { serde_json::json!({"schemaVersion":"d4planner-local-planner/v1",
        "status":"READY","url":url,"snapshotId":"fixture-ui","manifestSha256":"a".repeat(64),"reused":true}) }
    #[test]
    fn browser_opens_only_verified_ready_once() {
        let pending = AtomicBool::new(false);
        let opened = AtomicBool::new(false);
        let value = open(&pending, 6085, || Ok(ready("http://127.0.0.1:6085/")), |url| {
            assert_eq!(url,"http://127.0.0.1:6085/"); opened.store(true,Ordering::Relaxed); Ok(())
        }).unwrap();
        assert!(value.reused && opened.load(Ordering::Relaxed)); assert!(!pending.load(Ordering::Relaxed));
    }
    #[test]
    fn unsafe_or_wrong_port_urls_and_failed_responses_never_open() {
        for url in ["https://maxroll.gg/", "http://localhost:6085/", "http://127.0.0.1:6086/", "http://127.0.0.1:6085/?x=1", "http://127.0.0.1:6085/@evil", "file:///x", "http://127.0.0.1:6085/\n"] {
            assert!(open(&AtomicBool::new(false),6085,||Ok(ready(url)), |_|panic!("must not open")).is_err());
        }
        let mut value=ready("http://127.0.0.1:6085/");value["status"]="STARTING".into();
        assert!(open(&AtomicBool::new(false),6085,||Ok(value), |_|panic!("must not open")).is_err());
    }
    #[test]
    fn snapshot_and_port_errors_never_open_browser() {
        for code in ["PLANNER_SNAPSHOT_UNAVAILABLE", "PLANNER_SNAPSHOT_UNTRUSTED", "PLANNER_PORT_CONFLICT"] {
            let pending = AtomicBool::new(false);
            assert_eq!(open(&pending, 6085, || Err(code.into()), |_| panic!("must not open")).unwrap_err(), code);
            assert!(!pending.load(Ordering::Relaxed));
        }
    }
    #[test]
    fn concurrent_open_is_busy_and_private_errors_are_redacted() {
        let pending=AtomicBool::new(false);
        let _=open(&pending,6085,|| {
            assert_eq!(open(&pending,6085,||panic!(), |_|panic!()).unwrap_err(),"PLANNER_BUSY");
            Err("private path /secret".into())
        }, |_|panic!());
        assert!(!pending.load(Ordering::Relaxed));
        assert_eq!(safe_error("private path /secret"),"PLANNER_UNAVAILABLE");
    }
}
