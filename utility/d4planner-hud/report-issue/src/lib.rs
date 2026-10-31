//! Native-only diagnostics. No arbitrary file paths accepted from the WebView.
use d4planner_runtime_logging::{export_selected, safe};
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};
pub type Result<T> = std::result::Result<T, String>;
const MAX: u64 = 64_000_000; // safety ceiling, deployment can only reduce it
fn error(_: impl std::fmt::Debug) -> String {
    "DIAGNOSTIC_IO_FAILED".into()
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Selection {
    pub fe: bool,
    pub be: bool,
    pub rulekit: bool,
    pub evidence: bool,
    pub evidence_consent: bool,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Description {
    pub issue_type: String,
    pub title: String,
    pub actual: String,
    pub expected: String,
    pub steps: String,
}
impl Description {
    pub fn validate(&self) -> Result<()> {
        if ![
            "Incorrect Equipment",
            "Crash / Startup",
            "HUD / Display",
            "Rule Kit / Calculation",
            "Other",
        ]
        .contains(&self.issue_type.as_str())
            || self.title.trim().is_empty()
            || self.title.chars().count() > 100
            || self.actual.trim().is_empty()
            || self.expected.trim().is_empty()
            || [&self.actual, &self.expected, &self.steps]
                .iter()
                .any(|s| s.len() > 8000 || s.contains('\0'))
        {
            return Err("INVALID_FORM".into());
        }
        Ok(())
    }
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Config {
    pub recipient: String,
    pub gateway: String,
    pub max_bytes: u64,
}
impl Config {
    pub fn validate(&self) -> Result<()> {
        self.recipient
            .parse::<age::x25519::Recipient>()
            .map_err(|_| "RECIPIENT_NOT_CONFIGURED")?;
        let u = reqwest::Url::parse(&self.gateway).map_err(|_| "GATEWAY_NOT_CONFIGURED")?;
        if u.scheme() != "https"
            || !u.username().is_empty()
            || u.password().is_some()
            || u.query().is_some()
            || u.fragment().is_some()
            || self.max_bytes == 0
            || self.max_bytes > MAX
        {
            return Err("INVALID_REPORT_CONFIG".into());
        }
        Ok(())
    }
}
/// A single pending report, owned by native state. RAII cleans private plaintext on errors/cancel.
pub struct Report {
    pub id: String,
    pub preview: Value,
    dir: PathBuf,
    sealed: Option<PathBuf>,
    lock: Option<File>,
}
impl Drop for Report {
    fn drop(&mut self) {
        if let Some(lock) = self.lock.take() {
            let _ = FileExt::unlock(&lock);
            drop(lock);
        }
        if self.sealed.is_none() && safe(&self.dir) {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }
}
fn create(path: &Path) -> Result<File> {
    let mut o = OpenOptions::new();
    o.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.mode(0o600);
    }
    o.open(path).map_err(error)
}
fn private_dir(path: &Path) -> Result<()> {
    d4planner_runtime_logging::private_dir(path).map_err(error)
}
impl Report {
    pub fn discard(mut self) {
        self.sealed = None;
        drop(self);
    }
    pub fn restored_preview(&self) -> Value {
        let mut preview = self.preview.clone();
        if let Ok(bytes) = fs::read(self.dir.join("description.json")) {
            if bytes.len() <= 30_000 {
                if let Ok(d) = serde_json::from_slice::<Description>(&bytes) {
                    preview["description"] = json!(d);
                }
            }
        }
        preview
    }
    pub fn resume(data: &Path, id: &str) -> Result<Self> {
        if uuid::Uuid::parse_str(id).is_err() {
            return Err("INVALID_REPORT_ID".into());
        }
        let dir = data.join("private").join(format!("report-{id}"));
        if !safe(&dir) || fs::read(dir.join("owner.json")).map_err(error)? != b"d4planner-report/v1"
        {
            return Err("INVALID_REPORT".into());
        }
        for name in [
            "owner.lock",
            "sealed.json",
            "report.zip.age",
            "description.json",
        ] {
            if !safe(&dir.join(name)) {
                return Err("UNSAFE_PATH".into());
            }
        }
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .open(dir.join("owner.lock"))
            .map_err(error)?;
        lock.try_lock_exclusive().map_err(|_| "REPORT_BUSY")?;
        if fs::metadata(dir.join("sealed.json")).map_err(error)?.len() > 65_536
            || fs::metadata(dir.join("report.zip.age"))
                .map_err(error)?
                .len()
                > MAX
        {
            return Err("REPORT_TOO_LARGE".into());
        }
        let m: Value = serde_json::from_slice(&fs::read(dir.join("sealed.json")).map_err(error)?)
            .map_err(error)?;
        if m["preview"]["reportId"] != id
            || m["cipherSha256"]
                != json!(hash(&fs::read(dir.join("report.zip.age")).map_err(error)?))
        {
            return Err("INVALID_REPORT".into());
        }
        Ok(Self {
            id: id.into(),
            preview: m["preview"].clone(),
            sealed: Some(dir.join("report.zip.age")),
            dir,
            lock: Some(lock),
        })
    }
    pub fn collect(
        data: &Path,
        run: &str,
        selection: Selection,
        evidence: impl FnOnce(&Path) -> Result<Value>,
    ) -> Result<Self> {
        if selection.evidence && !selection.evidence_consent {
            return Err("EVIDENCE_CONSENT_REQUIRED".into());
        }
        if uuid::Uuid::parse_str(run).is_err()
            && (selection.fe || selection.be || selection.rulekit)
        {
            return Err("INVALID_RUN_ID".into());
        }
        if !data.is_absolute() || !safe(data) {
            return Err("INVALID_DATA_ROOT".into());
        }
        let base = data.join("private");
        if !base.exists() {
            private_dir(&base)?;
        }
        if !safe(&base) {
            return Err("UNSAFE_PATH".into());
        }
        // Bounded pending storage. Never silently erase encrypted drafts awaiting reconciliation.
        let mut pending = 0;
        for entry in fs::read_dir(&base).map_err(error)? {
            let p = entry.map_err(error)?.path();
            if !p
                .file_name()
                .and_then(|x| x.to_str())
                .unwrap_or("")
                .starts_with("report-")
                || !safe(&p)
            {
                continue;
            }
            if fs::read(p.join("owner.json")).ok().as_deref() != Some(b"d4planner-report/v1") {
                continue;
            }
            if let Ok(lock) = OpenOptions::new()
                .read(true)
                .write(true)
                .open(p.join("owner.lock"))
            {
                if lock.try_lock_exclusive().is_ok() {
                    let sealed = p.join("sealed.json").is_file();
                    let _ = FileExt::unlock(&lock);
                    drop(lock);
                    if !sealed {
                        if fs::remove_dir_all(&p).is_err() {
                            pending += 1;
                        }
                    } else {
                        pending += 1;
                    }
                } else {
                    pending += 1;
                }
            }
        }
        if pending >= 3 {
            return Err("PENDING_REPORT_LIMIT".into());
        }
        let id = uuid::Uuid::new_v4().to_string();
        let dir = base.join(format!("report-{id}"));
        private_dir(&dir)?;
        let lock = create(&dir.join("owner.lock"))?;
        lock.try_lock_exclusive().map_err(error)?;
        let mut report = Self {
            id,
            dir,
            preview: Value::Null,
            sealed: None,
            lock: Some(lock),
        };
        create(&report.dir.join("owner.json"))?
            .write_all(b"d4planner-report/v1")
            .map_err(error)?;
        let selected: Vec<&str> = [
            ("FE", selection.fe),
            ("BE", selection.be),
            ("RULEKIT", selection.rulekit),
        ]
        .into_iter()
        .filter_map(|(n, b)| b.then_some(n))
        .collect();
        // Session metadata is independent of selected log content (including zero sources).
        let mut source = export_selected(data,run,&report.dir.join("logs"),&selected).unwrap_or_else(|_|json!({"files":selected.iter().map(|s|json!({"name":match *s {"FE"=>"fe.log","BE"=>"be.log",_=>"rulekit.log"},"status":"UNAVAILABLE"})).collect::<Vec<_>>(),"completeness":"UNAVAILABLE"}));
        let mut files = Vec::new();
        for item in source["files"].as_array().ok_or("INVALID_EXPORT")? {
            let mut item = item.clone();
            item["path"] = json!(format!(
                "logs/{}",
                item["name"].as_str().ok_or("INVALID_EXPORT")?
            ));
            files.push(item);
        }
        if selection.evidence {
            let exported=evidence(&report.dir.join("evidence")).unwrap_or_else(|_|json!({"files":[{"name":"events.db","status":"UNAVAILABLE"},{"name":"equipment-projector.jsonl","status":"UNAVAILABLE"}]}));
            for item in exported["files"]
                .as_array()
                .ok_or("INVALID_EVIDENCE_EXPORT")?
            {
                let mut item = item.clone();
                item["path"] = json!(format!(
                    "evidence/{}",
                    item["name"].as_str().ok_or("INVALID_EXPORT")?
                ));
                files.push(item);
            }
        }
        let mut total = 0;
        for item in &mut files {
            let path = item["path"].as_str().ok_or("INVALID_EXPORT")?;
            if ![
                "logs/fe.log",
                "logs/be.log",
                "logs/rulekit.log",
                "evidence/events.db",
                "evidence/equipment-projector.jsonl",
            ]
            .contains(&path)
            {
                return Err("INVALID_EXPORT_PATH".into());
            }
            let p = report.dir.join(path);
            if !safe(&p) {
                return Err("UNSAFE_PATH".into());
            }
            if item["status"] == "UNAVAILABLE" || !p.exists() {
                item["status"] = json!("UNAVAILABLE");
                continue;
            }
            let n = fs::metadata(&p).map_err(error)?.len();
            total += n;
            if total > MAX {
                return Err("REPORT_TOO_LARGE".into());
            }
            let bytes = fs::read(&p).map_err(error)?;
            item["bytes"] = json!(bytes.len());
            item["sha256"] = json!(hash(&bytes));
            item["status"] = json!("BEST_EFFORT");
        }
        report.preview = json!({"schemaVersion":"d4planner-issue-report/v1","reportId":report.id,"runId":run,"timestamp":d4planner_runtime_logging::now(),"productVersion":source["productVersion"].take(),"sourceVersion":source["sourceVersion"].take(),"consent":selection,"files":files,"bytes":total,"completeness":if total==0{"EMPTY"}else{"BEST_EFFORT"}});
        Ok(report)
    }
    pub fn encrypt(&mut self, config: &Config) -> Result<Value> {
        config.validate()?;
        if self.preview["bytes"].as_u64().unwrap_or(MAX + 1) > config.max_bytes {
            return Err("REPORT_TOO_LARGE".into());
        }
        if self.sealed.is_none() {
            // Retry an interrupted local encryption without reusing partial ciphertext.
            for name in ["report.zip", "report.zip.age", "sealed.json"] {
                let p = self.dir.join(name);
                if !safe(&p) {
                    return Err("UNSAFE_PATH".into());
                }
                if p.exists() {
                    fs::remove_file(p).map_err(error)?;
                }
            }
            let path = self.dir.join("report.zip");
            let mut zip = zip::ZipWriter::new(create(&path)?);
            let options = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated)
                .compression_level(Some(9));
            zip.start_file("manifest.json", options).map_err(error)?;
            zip.write_all(&serde_json::to_vec(&self.preview).map_err(error)?)
                .map_err(error)?;
            for f in self.preview["files"].as_array().ok_or("INVALID_EXPORT")? {
                if f["status"] == "UNAVAILABLE" {
                    continue;
                }
                let name = f["path"].as_str().ok_or("INVALID_EXPORT")?;
                let bytes = fs::read(self.dir.join(name)).map_err(error)?;
                if json!(hash(&bytes)) != f["sha256"] {
                    return Err("EXPORT_CHANGED".into());
                }
                zip.start_file(name, options).map_err(error)?;
                zip.write_all(&bytes).map_err(error)?;
            }
            zip.finish().map_err(error)?.sync_all().map_err(error)?;
            let recipient = config
                .recipient
                .parse::<age::x25519::Recipient>()
                .map_err(error)?;
            let encryptor =
                age::Encryptor::with_recipients(std::iter::once(&recipient as &dyn age::Recipient))
                    .map_err(error)?;
            let sealed = self.dir.join("report.zip.age");
            let mut writer = encryptor.wrap_output(create(&sealed)?).map_err(error)?;
            std::io::copy(&mut File::open(&path).map_err(error)?, &mut writer).map_err(error)?;
            writer.finish().map_err(error)?.sync_all().map_err(error)?;
            fs::remove_file(path).map_err(error)?;
            if fs::metadata(&sealed).map_err(error)?.len() > config.max_bytes {
                return Err("REPORT_TOO_LARGE".into());
            }
            let metadata = json!({"preview":self.preview,"cipherSha256":hash(&fs::read(&sealed).map_err(error)?),"recipientSha256":hash(config.recipient.as_bytes())});
            create(&self.dir.join("sealed.json"))?
                .write_all(&serde_json::to_vec(&metadata).map_err(error)?)
                .map_err(error)?;
            // No raw source snapshots retained after encryption. Ciphertext supports restart/reconcile.
            for name in ["logs", "evidence"] {
                let p = self.dir.join(name);
                if p.exists() {
                    fs::remove_dir_all(p).map_err(error)?;
                }
            }
            self.sealed = Some(sealed);
        }
        let stored: Value =
            serde_json::from_slice(&fs::read(self.dir.join("sealed.json")).map_err(error)?)
                .map_err(error)?;
        if stored["recipientSha256"] != json!(hash(config.recipient.as_bytes())) {
            return Err("RECIPIENT_CHANGED".into());
        }
        let bytes = fs::read(self.sealed.as_ref().unwrap()).map_err(error)?;
        if stored["cipherSha256"] != json!(hash(&bytes)) {
            return Err("CIPHERTEXT_CHANGED".into());
        }
        Ok(json!({"reportId":self.id,"sha256":hash(&bytes),"bytes":bytes.len()}))
    }
    pub fn submit(
        &mut self,
        config: &Config,
        description: &Description,
        access_token: &str,
        consent: bool,
    ) -> Result<Value> {
        if !consent {
            return Err("CONSENT_REQUIRED".into());
        }
        description.validate()?;
        let draft = self.dir.join("description.json");
        let serialized = serde_json::to_vec(description).map_err(error)?;
        if draft.exists() {
            if fs::read(&draft).map_err(error)? != serialized {
                return Err("SUBMITTED_DRAFT_IMMUTABLE".into());
            }
        } else {
            create(&draft)?.write_all(&serialized).map_err(error)?;
        }
        let artifact = self.encrypt(config)?;
        let client = reqwest::blocking::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .map_err(error)?;
        // Client sends ciphertext only. The short-lived user credential is never persisted.
        let response = client
            .put(format!(
                "{}/reports/{}",
                config.gateway.trim_end_matches('/'),
                self.id
            ))
            .bearer_auth(access_token)
            .json(&json!({"description":description,"artifact":artifact}))
            .send()
            .map_err(|_| "GATEWAY_OFFLINE")?;
        if !response.status().is_success() {
            return Err(format!("GATEWAY_{}", response.status().as_u16()));
        }
        let response = client
            .post(format!(
                "{}/reports/{}/asset",
                config.gateway.trim_end_matches('/'),
                self.id
            ))
            .bearer_auth(access_token)
            .header("Content-Type", "application/octet-stream")
            .body(fs::read(self.sealed.as_ref().unwrap()).map_err(error)?)
            .send()
            .map_err(|_| "UPLOAD_PENDING")?;
        if !response.status().is_success() {
            return Err(format!("GATEWAY_{}", response.status().as_u16()));
        }
        let mut bytes = Vec::new();
        response
            .take(65_537)
            .read_to_end(&mut bytes)
            .map_err(error)?;
        if bytes.len() > 65_536 {
            return Err("INVALID_GATEWAY_RESPONSE".into());
        }
        let value: Value = serde_json::from_slice(&bytes).map_err(error)?;
        let url = value["issueUrl"]
            .as_str()
            .ok_or("INVALID_GATEWAY_RESPONSE")?;
        if !url.starts_with("https://github.com/Synclab-VN-dev/StreamOps/issues/")
            || !url
                .rsplit('/')
                .next()
                .unwrap_or("")
                .bytes()
                .all(|b| b.is_ascii_digit())
        {
            return Err("INVALID_GATEWAY_RESPONSE".into());
        }
        Ok(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn temp() -> PathBuf {
        let p = std::env::temp_dir().join(format!("report-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&p).unwrap();
        p
    }
    fn selection() -> Selection {
        Selection {
            fe: true,
            be: false,
            rulekit: false,
            evidence: false,
            evidence_consent: false,
        }
    }
    #[test]
    fn selected_export_zip_age_roundtrip_and_resume() {
        let data = temp();
        let session =
            d4planner_runtime_logging::Session::create(&data, "1.2.8", "synthetic-source").unwrap();
        let mut report = Report::collect(&data, &session.id, selection(), |_| {
            panic!("unselected evidence read")
        })
        .unwrap();
        assert_eq!(report.preview["files"].as_array().unwrap().len(), 1);
        assert_eq!(report.preview["files"][0]["name"], "fe.log");
        let identity = age::x25519::Identity::generate();
        let config = Config {
            recipient: identity.to_public().to_string(),
            gateway: "https://gateway.invalid".into(),
            max_bytes: MAX,
        };
        let meta = report.encrypt(&config).unwrap();
        let sealed = fs::read(report.sealed.as_ref().unwrap()).unwrap();
        assert_eq!(meta["sha256"], hash(&sealed));
        assert!(!report.dir.join("report.zip").exists());
        assert!(!report.dir.join("logs").exists());
        let decrypt = age::Decryptor::new(&sealed[..]).unwrap();
        let mut reader = decrypt
            .decrypt(std::iter::once(&identity as &dyn age::Identity))
            .unwrap();
        let mut plain = Vec::new();
        reader.read_to_end(&mut plain).unwrap();
        let mut archive = zip::ZipArchive::new(std::io::Cursor::new(plain)).unwrap();
        assert_eq!(archive.len(), 2);
        assert_eq!(
            archive.by_name("logs/fe.log").unwrap().compression(),
            zip::CompressionMethod::Deflated
        );
        let mut m = String::new();
        archive
            .by_name("manifest.json")
            .unwrap()
            .read_to_string(&mut m)
            .unwrap();
        let m: Value = serde_json::from_str(&m).unwrap();
        assert_eq!(m, report.preview);
        let id = report.id.clone();
        drop(report);
        let mut resumed = Report::resume(&data, &id).unwrap();
        assert_eq!(resumed.encrypt(&config).unwrap(), meta);
        resumed.discard();
        drop(session);
        fs::remove_dir_all(data).unwrap();
    }
    #[test]
    fn consent_invalid_config_and_missing_sources() {
        let data = temp();
        let session = d4planner_runtime_logging::Session::create(&data, "1", "s").unwrap();
        let mut s = selection();
        s.evidence = true;
        assert!(Report::collect(&data, &session.id, s, |_| panic!()).is_err());
        let mut r = Report::collect(&data, &session.id, selection(), |_| panic!()).unwrap();
        assert!(r
            .encrypt(&Config {
                recipient: "".into(),
                gateway: "http://bad".into(),
                max_bytes: MAX
            })
            .is_err());
        r.discard();
        drop(session);
        fs::remove_dir_all(data).unwrap();
    }
    #[test]
    fn unsafe_run_and_symlink() {
        let data = temp();
        assert!(Report::collect(&data, "../private", selection(), |_| panic!()).is_err());
        fs::remove_dir_all(data).unwrap();
    }
    #[test]
    fn no_sources_produces_empty_manifest() {
        let data = temp();
        let mut s = selection();
        s.fe = false;
        let session =
            d4planner_runtime_logging::Session::create(&data, "1.2.8", "source-test").unwrap();
        let r = Report::collect(&data, &session.id, s, |_| panic!()).unwrap();
        assert_eq!(r.preview["productVersion"], "1.2.8");
        assert_eq!(r.preview["sourceVersion"], "source-test");
        assert_eq!(r.preview["completeness"], "EMPTY");
        assert_eq!(r.preview["files"], json!([]));
        r.discard();
        drop(session);
        fs::remove_dir_all(data).unwrap();
    }
}

#[cfg(test)]
mod negative_tests {
    use super::*;
    fn fixture() -> (PathBuf, d4planner_runtime_logging::Session) {
        let p = std::env::temp_dir().join(format!("report-negative-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&p).unwrap();
        let s = d4planner_runtime_logging::Session::create(&p, "1", "fixture").unwrap();
        (p, s)
    }
    fn selected() -> Selection {
        Selection {
            fe: true,
            be: false,
            rulekit: false,
            evidence: false,
            evidence_consent: false,
        }
    }
    #[test]
    fn unselected_corrupt_log_not_read_and_selected_missing_is_explicit() {
        let (p, s) = fixture();
        let env = s.environment();
        let logs = PathBuf::from(&env["D4_LOG_DIR"]);
        fs::write(logs.join("be.log"), b"PRIVATE_CANARY_NOT_JSON").unwrap();
        let r = Report::collect(&p, &s.id, selected(), |_| panic!()).unwrap();
        assert_eq!(r.preview["files"].as_array().unwrap().len(), 1);
        r.discard();
        fs::remove_file(logs.join("fe.log")).unwrap();
        let r = Report::collect(&p, &s.id, selected(), |_| panic!()).unwrap();
        assert_eq!(r.preview["files"][0]["status"], "UNAVAILABLE");
        r.discard();
        drop(s);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn tampered_ciphertext_and_recipient_change_rejected() {
        let (p, s) = fixture();
        let identity = age::x25519::Identity::generate();
        let mut c = Config {
            recipient: identity.to_public().to_string(),
            gateway: "https://gateway.invalid".into(),
            max_bytes: MAX,
        };
        let mut r = Report::collect(&p, &s.id, selected(), |_| panic!()).unwrap();
        r.encrypt(&c).unwrap();
        c.recipient = age::x25519::Identity::generate().to_public().to_string();
        assert!(r.encrypt(&c).is_err());
        fs::write(r.sealed.as_ref().unwrap(), b"tampered").unwrap();
        let id = r.id.clone();
        drop(r);
        assert!(Report::resume(&p, &id).is_err());
        drop(s);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn lock_prevents_second_owner_and_size_limit_fails_closed() {
        let (p, s) = fixture();
        let mut r = Report::collect(&p, &s.id, selected(), |_| panic!()).unwrap();
        let c = Config {
            recipient: age::x25519::Identity::generate().to_public().to_string(),
            gateway: "https://gateway.invalid".into(),
            max_bytes: 1,
        };
        assert!(r.encrypt(&c).is_err());
        assert!(Report::resume(&p, &r.id).is_err());
        r.discard();
        drop(s);
        fs::remove_dir_all(p).unwrap();
    }
}

#[cfg(test)]
mod evidence_failure_test {
    use super::*;
    #[test]
    fn failed_provider_partial_file_is_never_promoted_to_available() {
        let data = std::env::temp_dir().join(format!("evidence-failure-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&data).unwrap();
        let s = Selection {
            fe: false,
            be: false,
            rulekit: false,
            evidence: true,
            evidence_consent: true,
        };
        let r = Report::collect(&data, "no-runtime-run", s, |dest| {
            fs::create_dir(dest).unwrap();
            fs::write(dest.join("events.db"), b"INCOMPLETE_PRIVATE_DB").unwrap();
            Err("EVIDENCE_TIMEOUT".into())
        })
        .unwrap();
        assert_eq!(r.preview["files"][0]["status"], "UNAVAILABLE");
        assert_eq!(r.preview["bytes"], 0);
        r.discard();
        fs::remove_dir_all(data).unwrap();
    }
}
