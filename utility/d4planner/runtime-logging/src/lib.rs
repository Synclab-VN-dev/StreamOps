//! S8: bounded, private JSONL. Never accept raw messages, paths or exception text.
use fs2::FileExt;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    env,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc::{sync_channel, SyncSender},
        Arc,
    },
    time::SystemTime,
};
pub const LIMITS: [(&str, u64); 3] = [
    ("FE", 5_000_000),
    ("BE", 10_000_000),
    ("RULEKIT", 15_000_000),
];
pub const GLOBAL: u64 = 200_000_000;
const RESERVE: u64 = 60_065_536;
pub const TAGS: &[&str] = &[
    "logger",
    "launcher",
    "native",
    "webview",
    "websocket",
    "hud",
    "lifecycle",
    "capture",
    "target",
    "sqlite",
    "worker",
    "browser",
    "snapshot",
    "session",
    "api",
];
pub const EVENTS: &[&str] = &[
    "SESSION_HEADER",
    "START",
    "READY",
    "STOP",
    "ERROR",
    "RESTART",
    "EXIT",
    "CONNECT",
    "DISCONNECT",
    "RECONNECT",
    "STATE_CHANGE",
    "REQUEST",
    "RESULT",
    "TIMEOUT",
    "QUARANTINE",
    "CREATE",
    "CLOSE",
    "RECOVERY",
    "UNAVAILABLE",
    "LOG_TRIMMED",
    "LOG_DROPPED",
    "LEGACY_FROZEN",
    "DEBUG_PROBE",
];
const NUMBERS: &[&str] = &[
    "durationMs",
    "bytes",
    "count",
    "dropped",
    "trimmed",
    "exitCode",
    "revision",
    "queueDepth",
    "active",
    "ok",
    "retryable",
];
fn fail() -> std::io::Error {
    std::io::Error::other("LOG_UNAVAILABLE")
}
pub fn safe(path: &Path) -> bool {
    let mut p = Some(path);
    while let Some(v) = p {
        if let Ok(m) = fs::symlink_metadata(v) {
            if m.file_type().is_symlink() {
                return false;
            }
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                if m.file_attributes() & 0x400 != 0 {
                    return false;
                }
            }
        }
        p = v.parent();
    }
    true
}
#[cfg(windows)]
fn secure_windows(p: &Path) -> std::io::Result<()> {
    unsafe {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::{
            Foundation::LocalFree,
            Security::{
                Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW,
                SetFileSecurityW, DACL_SECURITY_INFORMATION, PROTECTED_DACL_SECURITY_INFORMATION,
            },
        };
        let mut sd = std::ptr::null_mut();
        let text: Vec<u16> = "D:P(A;OICI;FA;;;OW)"
            .encode_utf16()
            .chain(Some(0))
            .collect();
        if ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text.as_ptr(),
            1,
            &mut sd,
            std::ptr::null_mut(),
        ) == 0
        {
            return Err(fail());
        }
        let path: Vec<u16> = p.as_os_str().encode_wide().chain(Some(0)).collect();
        let ok = SetFileSecurityW(
            path.as_ptr(),
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            sd,
        );
        LocalFree(sd);
        if ok == 0 {
            return Err(fail());
        }
        Ok(())
    }
}
fn private_dir(p: &Path) -> std::io::Result<()> {
    if !safe(p) {
        return Err(fail());
    }
    fs::create_dir_all(p)?;
    #[cfg(windows)]
    {
        secure_windows(p)?;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(p, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}
fn create(p: &Path) -> std::io::Result<File> {
    if !safe(p) || (p.exists() && !p.is_file()) {
        return Err(fail());
    }
    let mut o = OpenOptions::new();
    o.create(true).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.mode(0o600);
    }
    o.open(p)
}
fn file_name(c: &str) -> &str {
    match c {
        "FE" => "fe.log",
        "BE" => "be.log",
        _ => "rulekit.log",
    }
}
pub fn now() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}
pub fn clean(level: &str, tag: &str, event: &str, fields: Value) -> Option<Value> {
    if !["DEBUG", "INFO", "WARN", "ERROR"].contains(&level)
        || !TAGS.contains(&tag)
        || !EVENTS.contains(&event)
    {
        return None;
    }
    let mut out = serde_json::Map::new();
    if let Some(m) = fields.as_object() {
        for k in NUMBERS {
            if let Some(v) = m.get(*k) {
                if v.is_boolean() || v.as_f64().is_some_and(|n| n.is_finite() && n.abs() <= 1e15) {
                    out.insert(k.to_string(), v.clone());
                }
            }
        }
    }
    if let Some(v) = fields.get("errorCode") {
        if [
            "INTERNAL",
            "TIMEOUT",
            "TARGET_INVALID",
            "TARGET_CHANGED",
            "SNAPSHOT_MISMATCH",
            "UNAVAILABLE",
            "CLEANUP_PENDING",
            "IO_ERROR",
            "STARTUP_FAILED",
            "INVALID_CONFIG",
            "UNKNOWN",
        ]
        .contains(&v.as_str().unwrap_or(""))
        {
            out.insert("errorCode".into(), v.clone());
        }
    }
    if let Some(id) = fields.get("correlationId").and_then(Value::as_str) {
        if uuid::Uuid::parse_str(id).is_ok() {
            out.insert("correlationId".into(), json!(id));
        }
    }
    Some(Value::Object(out))
}
fn record(run: &str, c: &str, g: u64, l: &str, t: &str, e: &str, mut f: Value) -> Value {
    let correlation = f
        .as_object_mut()
        .and_then(|m| m.remove("correlationId"))
        .and_then(|v| v.as_str().map(str::to_owned));
    let mut value = json!({"schemaVersion":"d4planner-runtime-log/v1","ts":now(),"level":l,"component":c,"tag":t,"event":e,"runId":run,"pid":std::process::id(),"generation":g,"fields":f});
    if let Some(id) = correlation {
        value["correlationId"] = json!(format!("{:x}", Sha256::digest(id.as_bytes())));
    }
    value
}
fn encoded(v: &Value) -> Vec<u8> {
    let mut b = serde_json::to_vec(v).unwrap_or_default();
    b.push(b'\n');
    b
}
fn read_lines(p: &Path, cap: u64) -> std::io::Result<Vec<Vec<u8>>> {
    if !safe(p) || !p.is_file() {
        return Err(fail());
    }
    let f = File::open(p)?;
    if f.metadata()?.len() > cap {
        return Err(fail());
    }
    let mut bytes = Vec::new();
    f.take(cap + 1).read_to_end(&mut bytes)?;
    Ok(bytes
        .split_inclusive(|b| *b == b'\n')
        .filter(|l| l.ends_with(b"\n") && serde_json::from_slice::<Value>(l).is_ok())
        .map(|l| l.to_vec())
        .collect())
}
/// One sink per component lifetime, no persistent target handle (Windows rename).
pub struct Sink {
    pub dir: PathBuf,
    pub run: String,
    pub component: String,
    pub generation: u64,
    pub cap: u64,
    pub dropped: u64,
    pub trimmed: u64,
    policy: Value,
}
impl Sink {
    pub fn from_env(component: &str, generation: u64) -> Option<Self> {
        let dir = PathBuf::from(env::var("D4_LOG_DIR").ok()?);
        let run = env::var("D4_LOG_RUN_ID").ok()?;
        if uuid::Uuid::parse_str(&run).is_err() || !dir.is_absolute() || !safe(&dir) {
            return None;
        }
        let cap = LIMITS.iter().find(|(c, _)| *c == component)?.1;
        let policy = serde_json::from_str(&env::var("D4_LOG_POLICY").unwrap_or_default())
            .unwrap_or(json!({}));
        Some(Self {
            dir,
            run,
            component: component.into(),
            generation,
            cap,
            dropped: 0,
            trimmed: 0,
            policy,
        })
    }
    pub fn emit(&mut self, level: &str, tag: &str, event: &str, fields: Value) {
        let Some(fields) = clean(level, tag, event, fields) else {
            self.dropped += 1;
            return;
        };
        let levels = ["DEBUG", "INFO", "WARN", "ERROR"];
        let minimum = self.policy[&self.component][tag]
            .as_str()
            .or_else(|| self.policy[&self.component]["*"].as_str())
            .unwrap_or("INFO");
        let threshold = levels.iter().position(|v| *v == minimum).unwrap_or(1);
        if levels.iter().position(|v| *v == level).unwrap_or(1) < threshold {
            return;
        }
        let r = record(
            &self.run,
            &self.component,
            self.generation,
            level,
            tag,
            event,
            fields,
        );
        if self.write(&r).is_err() {
            self.dropped += 1;
        }
    }
    fn write(&mut self, r: &Value) -> std::io::Result<()> {
        let p = self.dir.join(file_name(&self.component));
        if !safe(&p) || !p.is_file() {
            return Err(fail());
        }
        let b = encoded(r);
        if b.len() > 4096 {
            return Err(fail());
        }
        let len = fs::metadata(&p)?.len();
        if len > self.cap {
            return Err(fail());
        }
        // Repair incomplete final record after a killed writer before appending.
        let broken = if len > 0 {
            use std::io::{Seek, SeekFrom};
            let mut f = File::open(&p)?;
            f.seek(SeekFrom::End(-1))?;
            let mut x = [0];
            f.read_exact(&mut x)?;
            x[0] != b'\n'
        } else {
            false
        };
        if len + b.len() as u64 > self.cap || broken {
            let lines = read_lines(&p, self.cap)?;
            let keep = ((lines.len().saturating_sub(1) as f64) * 0.7).floor() as usize;
            let mut start = lines.len().saturating_sub(keep).max(1);
            let header = lines.first().cloned().unwrap_or_default();
            let mut retained: usize = lines[start.min(lines.len())..].iter().map(Vec::len).sum();
            while start < lines.len() && header.len() + retained + 8192 > self.cap as usize {
                retained -= lines[start].len();
                start += 1;
            }
            self.trimmed += start.saturating_sub(1) as u64;
            let mut next = header;
            for line in &lines[start.min(lines.len())..] {
                next.extend(line);
            }
            next.extend(encoded(&record(
                &self.run,
                &self.component,
                self.generation,
                "WARN",
                "logger",
                "LOG_TRIMMED",
                json!({"trimmed":self.trimmed,"dropped":self.dropped}),
            )));
            let tmp = self
                .dir
                .parent()
                .ok_or_else(fail)?
                .join(".control")
                .join(format!("{}-{}.tmp", self.run, self.component));
            if !safe(&tmp) || next.len() + b.len() > self.cap as usize {
                return Err(fail());
            }
            let mut f = create(&tmp)?;
            f.set_len(0)?;
            f.write_all(&next)?;
            f.sync_all()?;
            drop(f);
            fs::rename(&tmp, &p)?;
        }
        let mut f = OpenOptions::new().append(true).open(&p)?;
        f.write_all(&b)?;
        Ok(())
    }
}
#[derive(Clone)]
pub struct Logger {
    tx: SyncSender<(String, String, String, Value)>,
    pub dropped: Arc<AtomicU64>,
    pending: Arc<AtomicU64>,
}
impl Logger {
    pub fn start(component: &str, g: u64) -> Option<Self> {
        let mut sink = Sink::from_env(component, g)?;
        let (tx, rx) = sync_channel::<(String, String, String, Value)>(256);
        let dropped = Arc::new(AtomicU64::new(0));
        let d = dropped.clone();
        let pending = Arc::new(AtomicU64::new(0));
        let count = pending.clone();
        std::thread::spawn(move || {
            while let Ok((l, t, e, f)) = rx.recv() {
                let n = d.swap(0, Ordering::Relaxed);
                if n > 0 {
                    sink.emit("WARN", "logger", "LOG_DROPPED", json!({"dropped":n}));
                }
                sink.emit(&l, &t, &e, f);
                count.fetch_sub(1, Ordering::Relaxed);
            }
        });
        Some(Self {
            tx,
            dropped,
            pending,
        })
    }
    pub fn emit(&self, l: &str, t: &str, e: &str, f: Value) {
        let Some(f) = clean(l, t, e, f) else {
            self.dropped.fetch_add(1, Ordering::Relaxed);
            return;
        };
        self.pending.fetch_add(1, Ordering::Relaxed);
        if self.tx.try_send((l.into(), t.into(), e.into(), f)).is_err() {
            self.pending.fetch_sub(1, Ordering::Relaxed);
            self.dropped.fetch_add(1, Ordering::Relaxed);
        }
    }
    pub fn flush(&self) {
        let t = std::time::Instant::now();
        while self.pending.load(Ordering::Relaxed) > 0 && t.elapsed().as_millis() < 500 {
            std::thread::sleep(std::time::Duration::from_millis(1));
        }
    }
}
/// Root holds an OS lock for the whole owned job lifetime. PID is never ownership proof.
pub struct Session {
    pub dir: PathBuf,
    pub id: String,
    lock: File,
    root: PathBuf,
}
fn size(p: &Path) -> u64 {
    fs::read_dir(p)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| {
            let p = e.path();
            if !safe(&p) {
                0
            } else if p.is_dir() {
                size(&p)
            } else {
                e.metadata().map(|m| m.len()).unwrap_or(0)
            }
        })
        .sum()
}
fn housekeeping(root: &Path, needed: u64) -> std::io::Result<()> {
    let control = root.join(".control");
    let mut closed = Vec::new();
    let mut reserved = 0;
    for e in fs::read_dir(&control)? {
        let p = e?.path();
        if p.extension().and_then(|s| s.to_str()) != Some("json") || !safe(&p) {
            continue;
        }
        let Ok(m) = serde_json::from_slice::<Value>(&fs::read(&p)?) else {
            continue;
        };
        let Some(id) = m["runId"].as_str() else {
            continue;
        };
        if uuid::Uuid::parse_str(id).is_err() || m["schemaVersion"] != "d4planner-log-session/v1" {
            continue;
        }
        let Some(name) = m["directory"].as_str() else {
            continue;
        };
        if name.contains(['/', '\\']) || !name.ends_with(id) {
            continue;
        }
        let dir = root.join(name);
        if !safe(&dir) || !dir.is_dir() {
            continue;
        }
        let lock = create(&control.join(format!("{id}.lock")))?;
        if lock.try_lock_exclusive().is_err() {
            reserved += RESERVE;
            continue;
        }
        let age = m["createdMs"].as_u64().unwrap_or(u64::MAX);
        closed.push((age, dir, p, lock, id.to_string()));
    }
    closed.sort_by_key(|c| c.0);
    let now = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64;
    for (age, dir, meta, lock, id) in closed {
        let actual = size(root);
        if now.saturating_sub(age) <= 14 * 86400000 && actual + reserved + needed <= GLOBAL {
            continue;
        }
        let entries: Vec<_> = fs::read_dir(&dir)?.collect::<Result<_, _>>()?;
        if entries.len() != 3
            || entries.iter().any(|e| {
                !safe(&e.path())
                    || !e.file_type().map(|t| t.is_file()).unwrap_or(false)
                    || !["fe.log", "be.log", "rulekit.log"]
                        .contains(&e.file_name().to_string_lossy().as_ref())
            })
        {
            continue;
        }
        let owned = LIMITS.iter().all(|(component, cap)| {
            read_lines(&dir.join(file_name(component)), *cap)
                .ok()
                .and_then(|rows| {
                    rows.first()
                        .and_then(|line| serde_json::from_slice::<Value>(line).ok())
                })
                .is_some_and(|header| {
                    header["schemaVersion"] == "d4planner-runtime-log/v1"
                        && header["event"] == "SESSION_HEADER"
                        && header["runId"] == id
                        && header["component"] == *component
                })
        });
        if !owned {
            continue;
        }
        for e in entries {
            fs::remove_file(e.path())?;
        }
        fs::remove_dir(dir)?;
        fs::remove_file(meta)?;
        for (c, _) in LIMITS {
            let tmp = control.join(format!("{id}-{c}.tmp"));
            if safe(&tmp) && tmp.is_file() {
                fs::remove_file(tmp)?;
            }
        }
        drop(lock);
        let _ = fs::remove_file(control.join(format!("{id}.lock")));
    }
    if size(root) + reserved + needed > GLOBAL {
        return Err(fail());
    }
    Ok(())
}
impl Session {
    pub fn create(data: &Path, product: &str, source: &str) -> std::io::Result<Self> {
        let root = data.join("logs");
        private_dir(&root)?;
        private_dir(&root.join(".control"))?;
        let global = create(&root.join(".control/global.lock"))?;
        global.try_lock_exclusive()?;
        housekeeping(&root, RESERVE)?;
        let id = uuid::Uuid::new_v4().to_string();
        let name = format!("{}_{}", chrono::Utc::now().format("%Y%m%d-%H%M%S"), id);
        let dir = root.join(&name);
        private_dir(&dir)?;
        let lock = create(&root.join(".control").join(format!("{id}.lock")))?;
        lock.try_lock_exclusive()?;
        for (c, _) in LIMITS {
            let mut f = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(dir.join(file_name(c)))?;
            f.write_all(&encoded(&record(
                &id,
                c,
                0,
                "INFO",
                "logger",
                "SESSION_HEADER",
                json!({}),
            )))?;
        }
        let metadata = json!({"schemaVersion":"d4planner-log-session/v1","runId":id,"directory":name,"createdMs":SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap_or_default().as_millis() as u64,"productVersion":product,"sourceVersion":source});
        let mut f = create(&root.join(".control").join(format!("{id}.json")))?;
        f.write_all(&encoded(&metadata))?;
        drop(global);
        Ok(Self {
            dir,
            id,
            lock,
            root,
        })
    }
    pub fn housekeeping(&self) {
        if let Ok(g) = create(&self.root.join(".control/global.lock")) {
            if g.try_lock_exclusive().is_ok() {
                let _ = housekeeping(&self.root, 0);
            }
        }
    }
    pub fn environment(&self) -> BTreeMap<String, String> {
        BTreeMap::from([
            ("D4_LOG_DIR".into(), self.dir.to_string_lossy().into_owned()),
            ("D4_LOG_RUN_ID".into(), self.id.clone()),
        ])
    }
    pub fn bootstrap_event(&self, event: &str) {
        let mut sink = Sink {
            dir: self.dir.clone(),
            run: self.id.clone(),
            component: "FE".into(),
            generation: 0,
            cap: LIMITS[0].1,
            dropped: 0,
            trimmed: 0,
            policy: json!({}),
        };
        sink.emit(
            if event == "ERROR" { "ERROR" } else { "INFO" },
            "launcher",
            event,
            json!({}),
        );
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        let _ = self.lock.unlock();
        if let Ok(g) = create(&self.root.join(".control/global.lock")) {
            if g.try_lock_exclusive().is_ok() {
                let _ = housekeeping(&self.root, 0);
            }
        }
    }
}
/// Read-only bounded export to a new directory; never follows links or accepts arbitrary files.
pub fn export(data: &Path, id: &str, destination: &Path) -> std::io::Result<Value> {
    if uuid::Uuid::parse_str(id).is_err() || destination.exists() || !safe(destination) {
        return Err(fail());
    }
    let root = data.join("logs");
    if !destination.is_absolute()
        || destination.starts_with(&root)
        || destination
            .components()
            .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return Err(fail());
    }
    let meta = root.join(".control").join(format!("{id}.json"));
    if !safe(&meta) {
        return Err(fail());
    }
    let m: Value = serde_json::from_slice(&fs::read(meta)?).map_err(|_| fail())?;
    let name = m["directory"].as_str().ok_or_else(fail)?;
    if name.contains(['/', '\\']) || !name.ends_with(id) {
        return Err(fail());
    }
    let dir = root.join(name);
    private_dir(destination)?;
    let mut files = Vec::new();
    for (c, cap) in LIMITS {
        let lines = read_lines(&dir.join(file_name(c)), cap)?;
        let mut bytes = Vec::new();
        let mut generations = std::collections::BTreeSet::new();
        let mut dropped = 0;
        let mut trimmed = 0;
        for l in lines {
            let r: Value = serde_json::from_slice(&l).map_err(|_| fail())?;
            if r["runId"] != id || r["component"] != c {
                continue;
            }
            let Some(fields) = clean(
                r["level"].as_str().unwrap_or(""),
                r["tag"].as_str().unwrap_or(""),
                r["event"].as_str().unwrap_or(""),
                r["fields"].clone(),
            ) else {
                continue;
            };
            let mut out = record(
                id,
                c,
                r["generation"].as_u64().unwrap_or(0),
                r["level"].as_str().unwrap(),
                r["tag"].as_str().unwrap(),
                r["event"].as_str().unwrap(),
                fields,
            );
            out["pid"] = json!(r["pid"].as_u64().unwrap_or(0));
            if let Some(ts) = r["ts"].as_str() {
                if chrono::DateTime::parse_from_rfc3339(ts).is_ok() {
                    out["ts"] = json!(ts);
                }
            }
            if let Some(correlation) = r["correlationId"].as_str() {
                if correlation.len() == 64 && correlation.bytes().all(|b| b.is_ascii_hexdigit()) {
                    out["correlationId"] = json!(correlation);
                }
            }
            generations.insert(out["generation"].as_u64().unwrap_or(0));
            dropped += out["fields"]["dropped"].as_u64().unwrap_or(0);
            trimmed = trimmed.max(out["fields"]["trimmed"].as_u64().unwrap_or(0));
            bytes.extend(encoded(&out));
        }
        let hash = format!("{:x}", Sha256::digest(&bytes));
        let mut f = create(&destination.join(file_name(c)))?;
        f.write_all(&bytes)?;
        files.push(json!({"name":file_name(c),"component":c,"bytes":bytes.len(),"sha256":hash,"generations":generations,"dropped":dropped,"trimmed":trimmed}));
    }
    let report = json!({"schemaVersion":"d4planner-log-export/v1","runId":id,"timestamp":now(),"productVersion":m["productVersion"],"sourceVersion":m["sourceVersion"],"files":files,"completeness":"BEST_EFFORT_BOUNDED_SNAPSHOT"});
    let mut f = create(&destination.join("manifest.json"))?;
    f.write_all(&encoded(&report))?;
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn temp() -> PathBuf {
        let p = env::temp_dir().join(format!("d4-log-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&p).unwrap();
        p
    }
    #[test]
    fn session_three_files_export_and_privacy() {
        let p = temp();
        let s = Session::create(&p, "1.2.8", "abc").unwrap();
        s.bootstrap_event("START");
        s.bootstrap_event("ERROR");
        let rows = read_lines(&s.dir.join("fe.log"), 5_000_000).unwrap();
        let error: Value = serde_json::from_slice(rows.last().unwrap()).unwrap();
        assert_eq!(error["level"], "ERROR");
        assert_eq!(fs::read_dir(&s.dir).unwrap().count(), 3);
        let mut sink = Sink {
            dir: s.dir.clone(),
            run: s.id.clone(),
            component: "FE".into(),
            generation: 3,
            cap: 5_000_000,
            dropped: 0,
            trimmed: 0,
            policy: json!({"FE":{"*":"DEBUG"}}),
        };
        sink.emit(
            "DEBUG",
            "hud",
            "DEBUG_PROBE",
            json!({"password":"SECRET_CANARY","message":"SECRET_CANARY","ok":true}),
        );
        let out = p.join("export");
        export(&p, &s.id, &out).unwrap();
        let text = fs::read_to_string(out.join("fe.log")).unwrap();
        assert!(!text.contains("SECRET_CANARY"));
        assert!(text.contains("DEBUG_PROBE"));
        drop(s);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn compact_and_partial_crash_repair() {
        let p = temp();
        let s = Session::create(&p, "1.2.8", "abc").unwrap();
        let mut w = Sink {
            dir: s.dir.clone(),
            run: s.id.clone(),
            component: "FE".into(),
            generation: 1,
            cap: 20_000,
            dropped: 0,
            trimmed: 0,
            policy: json!({}),
        };
        for _ in 0..1000 {
            w.emit("INFO", "native", "STATE_CHANGE", json!({"count":3}));
            assert!(fs::metadata(s.dir.join("fe.log")).unwrap().len() <= w.cap);
        }
        OpenOptions::new()
            .append(true)
            .open(s.dir.join("fe.log"))
            .unwrap()
            .write_all(b"{partial")
            .unwrap();
        w.emit("ERROR", "native", "ERROR", json!({}));
        let text = fs::read_to_string(s.dir.join("fe.log")).unwrap();
        for l in text.lines() {
            serde_json::from_str::<Value>(l).unwrap();
        }
        assert!(text.contains("SESSION_HEADER"));
        assert!(text.contains("LOG_TRIMMED"));
        drop(s);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn active_lock_and_global_reservation() {
        let p = temp();
        let a = Session::create(&p, "1", "a").unwrap();
        let b = Session::create(&p, "1", "a").unwrap();
        let c = Session::create(&p, "1", "a").unwrap();
        assert!(Session::create(&p, "1", "a").is_err());
        assert!(a.dir.exists() && b.dir.exists() && c.dir.exists());
        drop((a, b, c));
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn expired_closed_only() {
        let p = temp();
        let s = Session::create(&p, "1", "a").unwrap();
        let id = s.id.clone();
        let dir = s.dir.clone();
        let m = p.join("logs/.control").join(format!("{id}.json"));
        let mut v: Value = serde_json::from_slice(&fs::read(&m).unwrap()).unwrap();
        v["createdMs"] = json!(1);
        fs::write(m, serde_json::to_vec(&v).unwrap()).unwrap();
        let other = Session::create(&p, "1", "a").unwrap();
        assert!(dir.exists());
        drop(s);
        assert!(!dir.exists());
        drop(other);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn actual_fe_limit_and_newest_record_retained() {
        let p = temp();
        let s = Session::create(&p, "1", "a").unwrap();
        let mut w = Sink {
            dir: s.dir.clone(),
            run: s.id.clone(),
            component: "FE".into(),
            generation: 1,
            cap: 5_000_000,
            dropped: 0,
            trimmed: 0,
            policy: json!({}),
        };
        for i in 0..23000 {
            w.emit("INFO", "hud", "STATE_CHANGE", json!({"count":i}));
        }
        assert!(fs::metadata(s.dir.join("fe.log")).unwrap().len() <= 5_000_000);
        let rows = read_lines(&s.dir.join("fe.log"), 5_000_000).unwrap();
        let last: Value = serde_json::from_slice(rows.last().unwrap()).unwrap();
        assert_eq!(last["fields"]["count"], 22999);
        assert!(w.trimmed > 0);
        drop(s);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn global_budget_counts_foreign_bytes_without_deleting_them() {
        let p = temp();
        let s = Session::create(&p, "1", "a").unwrap();
        let foreign = p.join("logs/foreign");
        fs::create_dir(&foreign).unwrap();
        let f = File::create(foreign.join("owner-file")).unwrap();
        f.set_len(150_000_000).unwrap();
        assert!(Session::create(&p, "1", "a").is_err());
        assert_eq!(
            fs::metadata(foreign.join("owner-file")).unwrap().len(),
            150_000_000
        );
        assert!(s.dir.exists());
        drop(f);
        drop(s);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn capacity_evicts_oldest_closed_run_before_new_reservation() {
        let p = temp();
        let mut dirs = Vec::new();
        for n in 0..3 {
            let s = Session::create(&p, "1", "a").unwrap();
            for (c, cap) in LIMITS {
                let path = s.dir.join(file_name(c));
                let header = fs::read(&path).unwrap();
                let row = encoded(&record(
                    &s.id,
                    c,
                    1,
                    "INFO",
                    "logger",
                    "STATE_CHANGE",
                    json!({}),
                ));
                let count = ((cap as usize - 100_000 - header.len()) / row.len()).min(100_000);
                let mut bytes = header;
                for _ in 0..count {
                    bytes.extend(&row);
                }
                fs::write(path, bytes).unwrap();
            }
            let meta = p.join("logs/.control").join(format!("{}.json", s.id));
            let mut value: Value = serde_json::from_slice(&fs::read(&meta).unwrap()).unwrap();
            value["createdMs"] = json!(value["createdMs"].as_u64().unwrap() - 30_000 + n * 1000);
            fs::write(meta, encoded(&value)).unwrap();
            dirs.push(s.dir.clone());
            drop(s);
        }
        let a = Session::create(&p, "1", "a").unwrap();
        let b = Session::create(&p, "1", "a").unwrap();
        assert!(!dirs[0].exists());
        assert!(dirs[1].exists() && dirs[2].exists());
        assert!(size(&p.join("logs")) + 2 * RESERVE <= GLOBAL);
        drop((a, b));
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn export_is_read_only_and_cannot_target_logs_root() {
        let p = temp();
        let s = Session::create(&p, "1", "a").unwrap();
        let before = fs::read(s.dir.join("fe.log")).unwrap();
        assert!(export(&p, &s.id, &p.join("logs/export")).is_err());
        let m = export(&p, &s.id, &p.join("export")).unwrap();
        assert_eq!(m["files"].as_array().unwrap().len(), 3);
        assert_eq!(before, fs::read(s.dir.join("fe.log")).unwrap());
        assert_eq!(fs::read_dir(p.join("export")).unwrap().count(), 4);
        drop(s);
        fs::remove_dir_all(p).unwrap();
    }
    #[cfg(unix)]
    #[test]
    fn symlink_refused() {
        let p = temp();
        let elsewhere = temp();
        std::os::unix::fs::symlink(&elsewhere, p.join("logs")).unwrap();
        assert!(Session::create(&p, "1", "a").is_err());
        assert_eq!(fs::read_dir(&elsewhere).unwrap().count(), 0);
        fs::remove_dir_all(p).unwrap();
        fs::remove_dir_all(elsewhere).unwrap();
    }
}
