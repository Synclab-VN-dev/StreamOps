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
        "runtime/chromium/chrome-win64/chrome.exe", "utility/d4planner/rulekit-worker/worker.js", "utility/d4-rulekit/snapshot-management/manage.js"] {
        if !seen.contains(name) { return Err(format!("Required resource absent: {name}")); }
    }
    Ok(manifest)
}

#[derive(Debug, PartialEq)]
struct EquipmentConfig { path: PathBuf, character_id: String, display_name: String }

fn equipment_config(data: &Path) -> Result<Option<EquipmentConfig>, String> {
    let path = data.join("launcher.json");
    if !path.exists() { return Ok(None); }
    let value: Value = serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
        .map_err(|_| "Invalid launcher.json")?;
    if value["schemaVersion"] != "d4planner-launcher/v1" { return Err("Invalid launcher configuration version".into()); }
    if value.get("equipmentRepository").is_none() { return Ok(None); }
    let repository = &value["equipmentRepository"];
    match repository["enabled"].as_bool() {
        Some(false) if repository.as_object().is_some_and(|v| v.len() == 1) => return Ok(None),
        Some(true) => (),
        _ => return Err("Equipment repository requires explicit enabled=true and complete configuration".into()),
    }
    let string = |key: &str| -> Result<String, String> {
        let text = repository[key].as_str().ok_or_else(|| format!("Equipment {key} is required"))?;
        if text.trim().is_empty() || text.chars().any(char::is_control) || text.chars().count() > 160 && key != "path" {
            return Err(format!("Invalid Equipment {key}"));
        }
        Ok(text.to_owned())
    };
    let db = PathBuf::from(string("path")?);
    if !db.is_absolute() || !db.is_file() || fs::symlink_metadata(&db).map_err(|e| e.to_string())?.file_type().is_symlink() {
        return Err("Equipment DB must be an absolute existing regular file".into());
    }
    Ok(Some(EquipmentConfig { path:db, character_id:string("characterId")?, display_name:string("characterDisplayName")? }))
}

fn main() {
    let result = run();
    if let Ok(path) = env::var("D4PLANNER_LAUNCH_REPORT") {
        let report = json!({"ok":result.is_ok(),"error":result.as_ref().err(),"pid":std::process::id()});
        let _ = fs::write(path, report.to_string());
    }
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
    if root.join("upgrade-journal.json").exists() && !env::args().any(|a| a == "--installation-health" || a == "--runtime-health") {
        return Err("An interrupted upgrade needs Setup recovery before launch".into());
    }
    // Windows canonicalize returns a verbatim \\?\ path. Keep canonical paths
    // for containment checks, but give Node/CommonJS ordinary Win32 paths.
    // Node's relative module resolver does not support verbatim module roots.
    let payload = dunce::simplified(&payload(&root)?).to_path_buf();
    if env::args().any(|a| a == "--installation-health") { verify(&payload)?; return Ok(()); }
    #[cfg(windows)] {
        if env::args().any(|a| a == "--export-logs") {
            let args:Vec<String>=env::args().collect();
            let i=args.iter().position(|a|a=="--export-logs").unwrap();
            let id=args.get(i+1).ok_or("Run ID required")?;
            let destination=args.get(i+2).ok_or("New private export directory required")?;
            d4planner_runtime_logging::export(&windows::data_root(&root)?,id,Path::new(destination)).map_err(|_|"Log export unavailable")?;
            return Ok(());
        }
        if env::args().any(|a| a == "--snapshot-command") { verify(&payload)?; return windows::provision(&root, &payload); }
        windows::launch(&root, &payload, env::args().any(|a| a == "--runtime-health"))
    }
    #[cfg(not(windows))] { Err("D4Planner native launch requires Windows".into()) }
}

#[cfg(windows)]
mod windows {
    use super::*;
    use std::{os::windows::process::CommandExt, process::{Command, Stdio}, time::{Duration, Instant}};
    use windows_sys::Win32::{Foundation::*, System::{Console::*, JobObjects::*, Threading::*}, UI::WindowsAndMessaging::*};

    struct Handle(HANDLE);
    impl Drop for Handle { fn drop(&mut self) { unsafe { if !self.0.is_null() { CloseHandle(self.0); } } } }
    struct OwnedJob(HANDLE);
    impl Drop for OwnedJob {
        fn drop(&mut self) { unsafe {
            if self.0.is_null() { return; }
            TerminateJobObject(self.0, 0);
            let started = Instant::now();
            let mut accounting: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = std::mem::zeroed();
            while started.elapsed() < Duration::from_secs(5) {
                if QueryInformationJobObject(self.0, JobObjectBasicAccountingInformation,
                    &mut accounting as *mut _ as *mut _, std::mem::size_of_val(&accounting) as u32,
                    std::ptr::null_mut()) == 0 || accounting.ActiveProcesses == 0 { break; }
                std::thread::sleep(Duration::from_millis(50));
            }
            CloseHandle(self.0);
        } }
    }
    struct OwnedConsole(bool);
    impl Drop for OwnedConsole { fn drop(&mut self) { unsafe { if self.0 { FreeConsole(); } } } }
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
        // Tao/WebView2 also own hidden event-dispatch windows. Closing those
        // can strand the event loop before Tauri receives main-window close.
        if pid == parameter as u32 && IsWindowVisible(hwnd) != 0 {
            let mut title = [0u16; 256];
            let length = GetWindowTextW(hwnd, title.as_mut_ptr(), title.len() as i32);
            if String::from_utf16_lossy(&title[..length.max(0) as usize]) == "D4Planner Equipment HUD" {
                PostMessageW(hwnd, WM_CLOSE, 0, 0);
                return 0;
            }
        }
        1
    }

    pub(super) fn data_root(root: &Path) -> Result<PathBuf, String> {
        let installed = fs::read(root.join("active.json")).ok()
            .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
            .and_then(|state| state["dataDir"].as_str().map(PathBuf::from));
        let data = env::var_os("D4PLANNER_DATA_ROOT").map(PathBuf::from).or(installed).unwrap_or_else(||
            PathBuf::from(env::var_os("LOCALAPPDATA").unwrap_or_default()).join("StreamOps/D4Planner"));
        if !data.is_absolute() || data.starts_with(root) { return Err("DataDir must be absolute and outside installation".into()); }
        Ok(data)
    }

    pub fn provision(root: &Path, payload: &Path) -> Result<(), String> { unsafe {
        let args: Vec<String> = env::args().collect();
        let required = |name: &str| -> Result<String, String> {
            let index = args.iter().position(|value| value == name).ok_or_else(|| format!("{name} is required"))?;
            args.get(index+1).cloned().ok_or_else(|| format!("{name} value is required"))
        };
        let mut command = Command::new(payload.join("runtime/node/node.exe"));
        command.arg(payload.join("utility/d4-rulekit/snapshot-management/manage.js"))
            .args(["--operation", &required("--snapshot-command")?])
            .arg("--data-root").arg(data_root(root)?.join("rulekit"))
            .arg("--installation-root").arg(payload)
            .args(["--report", &required("--report")?])
            .creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW)
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        if let Some(index) = args.iter().position(|value| value == "--request-file") {
            command.arg("--request-file").arg(args.get(index+1).ok_or("request file path required")?);
        }
        let job = OwnedJob(CreateJobObjectW(std::ptr::null(), std::ptr::null()));
        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if job.0.is_null() || SetInformationJobObject(job.0, JobObjectExtendedLimitInformation, &limits as *const _ as *const _, std::mem::size_of_val(&limits) as u32)==0 { return Err("Cannot own provisioning process".into()); }
        let mut child = command.spawn().map_err(|e|e.to_string())?;
        use std::os::windows::io::AsRawHandle;
        if AssignProcessToJobObject(job.0, child.as_raw_handle() as HANDLE)==0 {let _=child.kill();let _=child.wait();return Err("Cannot assign provisioning ownership".into());}
        #[link(name="ntdll")] extern "system" {fn NtResumeProcess(process: HANDLE)->i32;}
        if NtResumeProcess(child.as_raw_handle() as HANDLE)<0 {return Err("Cannot resume provisioning process".into());}
        let started=Instant::now();
        loop {
            if let Some(status)=child.try_wait().map_err(|e|e.to_string())? {return if status.success(){Ok(())}else{Err(format!("Rule Kit provisioning failed: {status}"))};}
            if started.elapsed()>Duration::from_secs(120){TerminateJobObject(job.0,124);let _=child.wait();return Err("Provisioning deadline exceeded; owned job reclaimed".into());}
            std::thread::sleep(Duration::from_millis(50));
        }
    } }

    pub fn launch(root: &Path, payload: &Path, probe: bool) -> Result<(), String> { unsafe {
        let mutex = Handle(CreateMutexW(std::ptr::null(), 1, name(root, "instance").as_ptr()));
        if mutex.0.is_null() { return Err("Cannot create instance mutex".into()); }
        if GetLastError() == ERROR_ALREADY_EXISTS { return Ok(()); }
        // Child console runtimes inherit this hidden, application-owned console.
        // Never hide a console inherited from the operator's terminal.
        let console = OwnedConsole(GetConsoleWindow().is_null() && AllocConsole() != 0);
        if console.0 { ShowWindow(GetConsoleWindow(), SW_HIDE); }
        let stop_event = Handle(CreateEventW(std::ptr::null(), 1, 0, name(root, "stop").as_ptr()));
        if stop_event.0.is_null() { return Err("Cannot create owned stop event".into()); }
        let probe_data = env::temp_dir().join(format!("D4Planner-runtime-health-{}", uuid::Uuid::new_v4()));
        let data = if probe { probe_data.clone() } else { data_root(root)? };

        if !data.is_absolute() || data.starts_with(root) { return Err("DataDir must be absolute and outside installation".into()); }
        for directory in ["targets", "state", "private"] { fs::create_dir_all(data.join(directory)).map_err(|e| e.to_string())?; }
        let manifest:Value=serde_json::from_slice(&fs::read(payload.join("release-manifest.json")).unwrap_or_default()).unwrap_or(json!({}));
        let log_session=d4planner_runtime_logging::Session::create(&data,manifest["version"].as_str().unwrap_or("UNKNOWN"),manifest["sourceHead"].as_str().unwrap_or("UNKNOWN")).ok();
        if let Some(session)=&log_session {session.bootstrap_event("START");if data.join("private/native-stderr.log").exists(){session.bootstrap_event("LEGACY_FROZEN");}}
        if let Err(error)=verify(payload){if let Some(session)=&log_session{session.bootstrap_event("ERROR");}return Err(error);}
        let capture = if probe { None } else { match equipment_config(&data){Ok(v)=>v,Err(error)=>{if let Some(session)=&log_session{session.bootstrap_event("ERROR");}return Err(error)}} };
        let log_policy=fs::read(data.join("launcher.json")).ok().and_then(|b|serde_json::from_slice::<Value>(&b).ok()).and_then(|v|v.get("logging").cloned()).unwrap_or(json!({}));
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
            let job = OwnedJob(CreateJobObjectW(std::ptr::null(), std::ptr::null()));
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if job.0.is_null() || SetInformationJobObject(job.0, JobObjectExtendedLimitInformation,
                &limits as *const _ as *const _, std::mem::size_of_val(&limits) as u32) == 0 {
                return Err("Cannot configure owned process job".into());
            }
            let mut command = Command::new(payload.join("app/d4planner-fe.exe"));
            if let Some(session)=&log_session {command.envs(session.environment());}
            else {command.env_remove("D4_LOG_DIR").env_remove("D4_LOG_RUN_ID");}
            command.env("D4_LOG_POLICY",log_policy.to_string());
            command.current_dir(payload).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::piped())
                .creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW)
                .env("D4PLANNER_BOOTSTRAP_FILE", &bootstrap)
                .env("D4PLANNER_BACKEND_PYTHON", payload.join("runtime/python/python.exe"))
                .env("PYTHONPATH", payload.join("backend/site-packages"))
                .env("D4PLANNER_REPOSITORY_ROOT", payload)
                .env("D4PLANNER_RULEKIT_EXECUTABLE", payload.join("runtime/node/node.exe"))
                .env("D4PLANNER_RULEKIT_WORKER", payload.join("utility/d4planner/rulekit-worker/worker.js"))
                .env("D4PLANNER_RULEKIT_WORKING_DIR", payload.join("utility/d4planner/rulekit-worker"))
                .env("D4_RULEKIT_DATA_ROOT", data.join("rulekit"))
                .env("D4_RULEKIT_INSTALLATION_ROOT", payload)
                .env_remove("D4_RULEKIT_PROFILE_JSON").env_remove("D4_RULEKIT_SNAPSHOT_ROOT")
                .env("D4_RULEKIT_CHROMIUM_EXECUTABLE", payload.join("runtime/chromium/chrome-win64/chrome.exe"))
                .env("D4PLANNER_WS_PORT_MODE", if port == 0 { "DYNAMIC" } else { "FIXED_APPROVED_UAT" })
                .env_remove("D4PLANNER_EQUIPMENT_EVIDENCE_FILE")
                .env_remove("D4PLANNER_EQUIPMENT_REPOSITORY_DB")
                .env_remove("D4PLANNER_CHARACTER_ID").env_remove("D4PLANNER_CHARACTER_DISPLAY_NAME");
            if let Some(config) = &capture {
                command.env("D4PLANNER_EQUIPMENT_REPOSITORY_DB", &config.path)
                    .env("D4PLANNER_CHARACTER_ID", &config.character_id)
                    .env("D4PLANNER_CHARACTER_DISPLAY_NAME", &config.display_name);
            }
            let probe_report = data.join("private/runtime-health.json");
            if probe { command.arg("--backend-self-test").env("D4_BACKEND_SMOKE_REPORT", &probe_report); }
            let mut child = command.spawn().map_err(|e| e.to_string())?;
            // Raw native stderr is drained and discarded; no credentials/paths reach disk.
            if let Some(mut stderr)=child.stderr.take(){std::thread::spawn(move||{let mut bytes=[0;4096];while let Ok(n)=stderr.read(&mut bytes){if n==0{break}}});}
            use std::os::windows::io::AsRawHandle;
            if AssignProcessToJobObject(job.0, child.as_raw_handle() as HANDLE) == 0 {
                let _ = child.kill(); let _ = child.wait(); return Err("Cannot assign owned FE process to job".into());
            }
            // NtResumeProcess resumes the suspended root only after the job owns it.
            #[link(name="ntdll")]
            extern "system" { fn NtResumeProcess(process: HANDLE) -> i32; }
            if NtResumeProcess(child.as_raw_handle() as HANDLE) < 0 { return Err("Cannot resume owned FE".into()); }
            let mut closing = None;
            let mut last_housekeeping=Instant::now();
            let started = Instant::now();
            loop {
                if last_housekeeping.elapsed()>Duration::from_secs(60){if let Some(session)=&log_session{session.housekeeping();}last_housekeeping=Instant::now();}
                if probe && started.elapsed() > Duration::from_secs(55) {
                    TerminateJobObject(job.0, 124); let _ = child.wait();
                    return Err("Runtime health deadline exceeded; owned job reclaimed".into());
                }
                if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                    if let Some(session)=&log_session {session.bootstrap_event(if status.success(){"EXIT"}else{"ERROR"});}
                    if !status.success() { return Err(format!("Native HUD exited: {status}")); }
                    if probe {
                        let report: Value = serde_json::from_slice(&fs::read(&probe_report).map_err(|e| e.to_string())?)
                            .map_err(|e| e.to_string())?;
                        for phase in ["ready", "restartedReady"] {
                            let ready = &report[phase];
                            if !["READY", "UNAVAILABLE"].contains(&ready["health"]["ruleKitWorker"].as_str().unwrap_or("")) || ready["health"]["wsTransport"] != "READY"
                                || ready["health"]["durableState"] != "READY" || ready["health"]["targetRepository"] != "READY"
                                || ready["wsEndpoint"]["port"].as_u64().unwrap_or(0) == 0 {
                                return Err("Runtime health did not prove mandatory service readiness".into());
                            }
                        }
                        if report["ok"] != true || report["finalState"] != "EXITED"
                            || report["restartedReady"]["generation"].as_u64() <= report["ready"]["generation"].as_u64() {
                            return Err("Runtime health did not prove restart and shutdown".into());
                        }
                        TerminateJobObject(job.0, 0);
                        let mut accounting: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = std::mem::zeroed();
                        let cleanup = Instant::now();
                        loop {
                            if QueryInformationJobObject(job.0, JobObjectBasicAccountingInformation,
                                &mut accounting as *mut _ as *mut _, std::mem::size_of_val(&accounting) as u32,
                                std::ptr::null_mut()) == 0 { return Err("Cannot verify probe process cleanup".into()); }
                            if accounting.ActiveProcesses == 0 { break; }
                            if cleanup.elapsed() > Duration::from_secs(5) { return Err("Probe cleanup deadline exceeded".into()); }
                            std::thread::sleep(Duration::from_millis(50));
                        }
                        let args: Vec<String> = env::args().collect();
                        let index = args.iter().position(|arg| arg == "--health-report").ok_or("Health report path required")?;
                        let output = args.get(index + 1).ok_or("Health report path required")?;
                        fs::write(output, json!({"ok":true,"runtimeReady":true,"ownedCleanup":true,
                            "probe":"FE_BACKEND_RULEKIT_PROCESS_CHROMIUM_RESTART_STOP","calculationAvailability":report["ready"]["health"]["ruleKitWorker"],"details":report}).to_string())
                            .map_err(|e| e.to_string())?;
                    }
                    return Ok(());
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
        if result.is_err(){if let Some(session)=&log_session{session.bootstrap_event("ERROR");}}
        let _ = fs::remove_file(bootstrap);
        if probe { let _ = fs::remove_dir_all(probe_data); }
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
    #[cfg(windows)]
    #[test] fn runtime_paths_do_not_use_verbatim_node_module_roots() {
        assert_eq!(dunce::simplified(Path::new(r"\\?\C:\Cài đặt D4Planner\versions\1.0.0")),
                   Path::new(r"C:\Cài đặt D4Planner\versions\1.0.0"));
    }
}

#[cfg(test)]
mod equipment_tests {
    use super::*;
    #[test] fn opt_in_configuration_is_explicit_validated_and_preserves_unicode() {
        let data = env::temp_dir().join(format!("launcher-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&data).unwrap();
        assert_eq!(equipment_config(&data).unwrap(), None);
        let db = data.join("Trang bị.sqlite"); fs::write(&db, b"fixture").unwrap();
        let mut config = json!({"schemaVersion":"d4planner-launcher/v1","equipmentRepository":{
            "enabled":true,"path":db,"characterId":"test-character","characterDisplayName":"Nhân vật synthetic"}});
        let write = |value: &Value| fs::write(data.join("launcher.json"), value.to_string()).unwrap();
        write(&config);
        assert_eq!(equipment_config(&data).unwrap().unwrap().character_id, "test-character");
        for field in ["characterId", "characterDisplayName", "path"] {
            let mut bad = config.clone(); bad["equipmentRepository"][field] = json!(""); write(&bad);
            assert!(equipment_config(&data).is_err());
        }
        config["equipmentRepository"]["enabled"] = json!(false); write(&config);
        assert!(equipment_config(&data).is_err()); // disabling cannot leave ambiguous source fields
        write(&json!({"schemaVersion":"d4planner-launcher/v1","equipmentRepository":{"enabled":false}}));
        assert_eq!(equipment_config(&data).unwrap(), None);
        fs::remove_dir_all(data).unwrap();
    }
}
