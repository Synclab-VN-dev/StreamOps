#![cfg_attr(windows, windows_subsystem = "windows")]

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{env, fs, io::Read, path::{Component, Path, PathBuf}};

fn digest(path: &Path) -> Result<String, String> {
    let mut file = fs::File::open(path).map_err(|e| e.to_string())?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if count == 0 { break; }
        hash.update(&buffer[..count]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn relative(root: &Path, name: &str) -> Result<PathBuf, String> {
    let path = Path::new(name);
    if name.contains(['\\', ':']) || path.components().any(|p| !matches!(p, Component::Normal(_))) {
        return Err(format!("Unsafe resource path: {name}"));
    }
    let value = root.join(path).canonicalize().map_err(|e| format!("Missing resource {name}: {e}"))?;
    let canonical = root.canonicalize().map_err(|e| e.to_string())?;
    if !value.starts_with(canonical) { return Err("Resource escaped installation".into()); }
    Ok(value)
}

fn payload(root: &Path) -> Result<PathBuf, String> {
    let active = root.join("active.json");
    if active.is_file() {
        let state: Value = serde_json::from_slice(&fs::read(active).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        if state["applicationId"] != "vn.synclab.d4planner" { return Err("Application identity mismatch".into()); }
        relative(root, state["payload"].as_str().ok_or("Missing active payload")?)
    } else { Ok(root.to_owned()) }
}

fn verify(root: &Path) -> Result<Value, String> {
    let manifest: Value = serde_json::from_slice(&fs::read(root.join("release-manifest.json")).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    if manifest["schemaVersion"] != "d4planner-release-manifest/v1" { return Err("Manifest version mismatch".into()); }
    let files = manifest["files"].as_array().ok_or("Missing files manifest")?;
    if files.is_empty() { return Err("Empty manifest".into()); }
    let mut seen = std::collections::HashSet::new();
    for entry in files {
        let name = entry["path"].as_str().ok_or("Missing file path")?;
        if !seen.insert(name.to_lowercase()) { return Err("Duplicate resource path".into()); }
        let file = relative(root, name)?;
        if fs::metadata(&file).map_err(|e| e.to_string())?.len() != entry["bytes"].as_u64().ok_or("Missing file size")?
            || digest(&file)? != entry["sha256"].as_str().ok_or("Missing file checksum")? {
            return Err(format!("Resource integrity failed: {name}"));
        }
    }
    for name in ["app/d4planner-fe.exe", "runtime/python/python.exe", "runtime/node/node.exe",
        "runtime/chromium/chrome-win64/chrome.exe", "utility/d4planner/rulekit-worker/worker.js"] {
        if !seen.contains(name) { return Err(format!("Required resource absent: {name}")); }
    }
    Ok(manifest)
}

fn main() {
    let result = run();
    if let Err(error) = result {
        #[cfg(windows)] unsafe {
            use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR};
            let message: Vec<u16> = format!("D4Planner: {error}").encode_utf16().chain(Some(0)).collect();
            let title: Vec<u16> = "D4Planner".encode_utf16().chain(Some(0)).collect();
            if !env::args().any(|a| a.starts_with("--")) { MessageBoxW(std::ptr::null_mut(), message.as_ptr(), title.as_ptr(), MB_ICONERROR); }
        }
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let root = env::current_exe().map_err(|e| e.to_string())?.parent().ok_or("No installation root")?.to_owned();
    #[cfg(windows)]
    if env::args().any(|a| a == "--stop") { return windows::stop(&root); }
    if root.join("upgrade-journal.json").exists() && !env::args().any(|a| a == "--installation-health") {
        return Err("An interrupted upgrade needs Setup recovery before launch".into());
    }
    let payload = payload(&root)?;
    verify(&payload)?;
    if env::args().any(|a| a == "--installation-health") { return Ok(()); }
    #[cfg(windows)] { windows::launch(&root, &payload) }
    #[cfg(not(windows))] { Err("D4Planner native launch requires Windows".into()) }
}

#[cfg(windows)]
mod windows {
    use super::*;
    use std::{os::windows::process::CommandExt, process::{Command, Stdio}, time::{Duration, Instant}};
    use windows_sys::Win32::{Foundation::*, System::{JobObjects::*, Threading::*}, UI::WindowsAndMessaging::*};

    struct Handle(HANDLE);
    impl Drop for Handle { fn drop(&mut self) { unsafe { if !self.0.is_null() { CloseHandle(self.0); } } } }
    fn wide(value: &str) -> Vec<u16> { value.encode_utf16().chain(Some(0)).collect() }
    fn name(root: &Path, suffix: &str) -> Vec<u16> {
        wide(&format!("Local\\D4Planner-{:x}-{suffix}", Sha256::digest(root.to_string_lossy().to_lowercase().as_bytes())))
    }

    pub fn stop(root: &Path) -> Result<(), String> { unsafe {
        let handle = OpenEventW(EVENT_MODIFY_STATE | 0x00100000, 0, name(root, "stop").as_ptr());
        if handle.is_null() {
            return if GetLastError() == ERROR_FILE_NOT_FOUND { Ok(()) } else { Err("Cannot open owned stop event".into()) };
        }
        let event = Handle(handle);
        if SetEvent(event.0) == 0 { return Err("Cannot request owned shutdown".into()); }
        // The launcher keeps a mutex until FE and its job have been cleaned up.
        for _ in 0..200 {
            let mutex = OpenMutexW(0x00100000, 0, name(root, "instance").as_ptr());
            if mutex.is_null() { return Ok(()); }
            let mutex = Handle(mutex);
            let wait = WaitForSingleObject(mutex.0, 100);
            if wait == WAIT_OBJECT_0 || wait == WAIT_ABANDONED { return Ok(()); }
        }
        Err("Owned application did not finish shutdown within 20 seconds".into())
    } }

    unsafe extern "system" fn close_window(hwnd: HWND, parameter: isize) -> i32 {
        let mut pid = 0;
        GetWindowThreadProcessId(hwnd, &mut pid);
        if pid == parameter as u32 { PostMessageW(hwnd, WM_CLOSE, 0, 0); }
        1
    }

    pub fn launch(root: &Path, payload: &Path) -> Result<(), String> { unsafe {
        let mutex = Handle(CreateMutexW(std::ptr::null(), 1, name(root, "instance").as_ptr()));
        if mutex.0.is_null() { return Err("Cannot create instance mutex".into()); }
        if GetLastError() == ERROR_ALREADY_EXISTS { return Ok(()); }
        let stop_event = Handle(CreateEventW(std::ptr::null(), 1, 0, name(root, "stop").as_ptr()));
        if stop_event.0.is_null() { return Err("Cannot create owned stop event".into()); }
        let installed_data = fs::read(root.join("active.json")).ok()
            .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
            .and_then(|state| state["dataDir"].as_str().map(PathBuf::from));
        let data = env::var_os("D4PLANNER_DATA_ROOT").map(PathBuf::from).or(installed_data).unwrap_or_else(||
            PathBuf::from(env::var_os("LOCALAPPDATA").unwrap_or_default()).join("StreamOps/D4Planner"));
        if !data.is_absolute() || data.starts_with(root) { return Err("DataDir must be absolute and outside installation".into()); }
        for directory in ["targets", "state", "private"] { fs::create_dir_all(data.join(directory)).map_err(|e| e.to_string())?; }
        let bootstrap = data.join("private").join(format!("bootstrap-{}.json", uuid::Uuid::new_v4()));
        let credential: [u8;32] = rand::random();
        let owner = uuid::Uuid::new_v4().to_string();
        let port = match env::var("D4PLANNER_WS_PORT_MODE").as_deref() {
            Ok("FIXED_APPROVED_UAT") => env::var("D4PLANNER_APPROVED_UAT_PORT")
                .map_err(|_| "Approved UAT port is required")?.parse::<u16>()
                .ok().filter(|p| *p != 0).ok_or("Invalid approved UAT port")?,
            Ok("DYNAMIC") | Err(_) => 0,
            _ => return Err("Invalid port mode".into()),
        };
        let descriptor = json!({
            "protocol":"d4planner-managed/v1", "contractVersion":"d4planner-r1-contract/1.0.0-candidate.5",
            "ownerInstanceId":owner, "childInstanceId":uuid::Uuid::new_v4().to_string(), "generation":1,
            "dataDir":data.join("state"), "targetFolder":data.join("targets"),
            "credential":credential.iter().map(|byte| format!("{byte:02x}")).collect::<String>(),
            "wsEndpoint":{"host":"127.0.0.1","port":port}
        });
        fs::write(&bootstrap, serde_json::to_vec(&descriptor).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        let result = (|| -> Result<(), String> {
            let job = Handle(CreateJobObjectW(std::ptr::null(), std::ptr::null()));
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if job.0.is_null() || SetInformationJobObject(job.0, JobObjectExtendedLimitInformation,
                &limits as *const _ as *const _, std::mem::size_of_val(&limits) as u32) == 0 {
                return Err("Cannot configure owned process job".into());
            }
            let mut command = Command::new(payload.join("app/d4planner-fe.exe"));
            command.current_dir(payload).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
                .creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW)
                .env("D4PLANNER_BOOTSTRAP_FILE", &bootstrap)
                .env("D4PLANNER_BACKEND_PYTHON", payload.join("runtime/python/python.exe"))
                .env("PYTHONPATH", payload.join("backend/site-packages"))
                .env("D4PLANNER_REPOSITORY_ROOT", payload)
                .env("D4PLANNER_RULEKIT_EXECUTABLE", payload.join("runtime/node/node.exe"))
                .env("D4PLANNER_RULEKIT_WORKER", payload.join("utility/d4planner/rulekit-worker/worker.js"))
                .env("D4PLANNER_RULEKIT_WORKING_DIR", payload.join("utility/d4planner/rulekit-worker"))
                .env("D4_RULEKIT_PROFILE_JSON", payload.join("config/maxroll-profile.json"))
                .env("D4_RULEKIT_SNAPSHOT_ROOT", payload.join("runtime/snapshots"))
                .env("D4_RULEKIT_CHROMIUM_EXECUTABLE", payload.join("runtime/chromium/chrome-win64/chrome.exe"))
                .env("D4PLANNER_WS_PORT_MODE", if port == 0 { "DYNAMIC" } else { "FIXED_APPROVED_UAT" })
                .env_remove("D4PLANNER_EQUIPMENT_EVIDENCE_FILE")
                .env_remove("D4PLANNER_EQUIPMENT_REPOSITORY_DB")
                .env_remove("D4PLANNER_CHARACTER_ID").env_remove("D4PLANNER_CHARACTER_DISPLAY_NAME");
            let mut child = command.spawn().map_err(|e| e.to_string())?;
            use std::os::windows::io::AsRawHandle;
            if AssignProcessToJobObject(job.0, child.as_raw_handle() as HANDLE) == 0 {
                let _ = child.kill(); let _ = child.wait(); return Err("Cannot assign owned FE process to job".into());
            }
            // NtResumeProcess resumes the suspended root only after the job owns it.
            #[link(name="ntdll")]
            extern "system" { fn NtResumeProcess(process: HANDLE) -> i32; }
            if NtResumeProcess(child.as_raw_handle() as HANDLE) < 0 { return Err("Cannot resume owned FE".into()); }
            let mut closing = None;
            loop {
                if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                    return if status.success() { Ok(()) } else { Err(format!("Native HUD exited: {status}")) };
                }
                if WaitForSingleObject(stop_event.0, 100) == WAIT_OBJECT_0 {
                    if closing.is_none() { EnumWindows(Some(close_window), child.id() as isize); closing = Some(Instant::now()); }
                    if closing.is_some_and(|time| time.elapsed() > Duration::from_secs(12)) {
                        TerminateJobObject(job.0, 124); let _ = child.wait();
                        return Err("Owned shutdown exceeded its deadline; owned job reclaimed".into());
                    }
                }
            }
        })();
        let _ = fs::remove_file(bootstrap);
        result
    } }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn unsafe_paths_fail_closed() {
        for name in ["../outside", "C:/outside", "app\\..\\outside", "/absolute"] {
            assert!(relative(Path::new("."), name).is_err());
        }
    }
}
