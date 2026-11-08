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
pub mod local_gateway;
pub type Result<T> = std::result::Result<T, String>;
const MAX: u64 = 64_000_000; // safety ceiling, deployment can only reduce it
fn error(_: impl std::fmt::Debug) -> String {
    "DIAGNOSTIC_IO_FAILED".into()
}
fn gateway_failure(status: u16, bytes: &[u8]) -> String {
    let value: Value = serde_json::from_slice(bytes).unwrap_or(Value::Null);
    match value["error"].as_str() {
        Some(
            code @ ("GITHUB_401"
            | "GITHUB_403"
            | "GITHUB_RATE_LIMIT"
            | "IDEMPOTENCY_CONFLICT"
            | "CREATE_OUTCOME_UNCERTAIN"
            | "RELEASE_IDENTITY_OR_IMMUTABILITY_BLOCKED"
            | "INVALID_CIPHERTEXT"),
        ) => code.into(),
        _ => format!("GATEWAY_{status}"),
    }
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
        let loopback = u.scheme() == "http"
            && u.host_str() == Some("127.0.0.1")
            && u.port().is_some_and(|port| port > 0)
            && u.path() == "/";
        if (u.scheme() != "https" && !loopback)
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
#[derive(Debug, Serialize)]
pub struct SubmissionFailure {
    pub code: String,
    pub state: &'static str,
}
impl SubmissionFailure {
    pub fn uncertain(code: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            state: "REMOTE_OUTCOME_UNCERTAIN",
        }
    }
    pub fn for_report(code: String, report: &Report) -> Self {
        Self {
            code,
            state: if report.pending_remote() {
                "REMOTE_OUTCOME_UNCERTAIN"
            } else {
                "LOCAL_FAILURE"
            },
        }
    }
}
fn read_json(path: &Path, limit: u64) -> Result<Value> {
    if !safe(path) {
        return Err("UNSAFE_PATH".into());
    }
    if fs::metadata(path).map_err(error)?.len() > limit {
        return Err("REPORT_TOO_LARGE".into());
    }
    serde_json::from_slice(&fs::read(path).map_err(error)?).map_err(error)
}
/// A single owned report. Drop releases locks; explicit discard removes durable drafts.
pub struct Report {
    pub id: String,
    pub preview: Value,
    dir: PathBuf,
    sealed: Option<PathBuf>,
    lock: Option<File>,
    remote_resolved: bool,
}
impl Drop for Report {
    fn drop(&mut self) {
        if let Some(lock) = self.lock.take() {
            let _ = FileExt::unlock(&lock);
            drop(lock);
        }
        if self.sealed.is_none()
            && !self.dir.join("draft.json").try_exists().unwrap_or(true)
            && !self
                .dir
                .join("description.json")
                .try_exists()
                .unwrap_or(true)
            && safe(&self.dir)
        {
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
    pub fn pending_remote(&self) -> bool {
        // Only the send boundary writes description.json. Legacy descriptions and
        // damaged ciphertext remain uncertain too, including filesystem errors.
        !self.remote_resolved
            && self
                .dir
                .join("description.json")
                .try_exists()
                .unwrap_or(true)
    }
    pub fn discard(mut self) -> Result<()> {
        if self.pending_remote() {
            return Err("REPORT_RECONCILIATION_REQUIRED".into());
        }
        if !safe(&self.dir) {
            return Err("UNSAFE_PATH".into());
        }
        if let Some(lock) = self.lock.take() {
            let _ = FileExt::unlock(&lock);
            drop(lock);
        }
        fs::remove_dir_all(&self.dir).map_err(error)
    }
    pub fn restored_preview(&self) -> Value {
        let mut preview = self.preview.clone();
        preview["pendingRemote"] = json!(self.pending_remote());
        if let Ok(draft) = read_json(&self.dir.join("draft.json"), 100_000) {
            if let Some(d) = draft.get("description") {
                if let Ok(d) = serde_json::from_value::<Description>(d.clone()) {
                    preview["description"] = json!(d);
                }
            }
        }
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
            "draft.json",
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
        if !dir.join("sealed.json").try_exists().map_err(error)? {
            // Never downgrade a remote intent with damaged/missing ciphertext.
            if dir.join("description.json").try_exists().map_err(error)? {
                return Err("INVALID_REPORT".into());
            }
            let draft = read_json(&dir.join("draft.json"), 100_000)?;
            if let Some(d) = draft.get("description") {
                serde_json::from_value::<Description>(d.clone()).map_err(|_| "INVALID_REPORT")?;
            }
            let preview = &draft["preview"];
            if draft["schemaVersion"] != "d4planner-local-draft/v1" || preview["reportId"] != id {
                return Err("INVALID_REPORT".into());
            }
            validate_sources(preview)?;
            let mut total = 0u64;
            for f in preview["files"].as_array().ok_or("INVALID_REPORT")? {
                if f["status"] == "UNAVAILABLE" {
                    continue;
                }
                let path = dir.join(f["path"].as_str().ok_or("INVALID_REPORT")?);
                if !safe(&path) {
                    return Err("UNSAFE_PATH".into());
                }
                total = total
                    .checked_add(fs::metadata(&path).map_err(error)?.len())
                    .ok_or("REPORT_TOO_LARGE")?;
                if total > MAX {
                    return Err("REPORT_TOO_LARGE".into());
                }
                let bytes = fs::read(path).map_err(error)?;
                if f["sha256"] != hash(&bytes) || f["bytes"] != bytes.len() {
                    return Err("EXPORT_CHANGED".into());
                }
            }
            return Ok(Self {
                id: id.into(),
                preview: preview.clone(),
                dir,
                sealed: None,
                lock: Some(lock),
                remote_resolved: false,
            });
        }
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
        validate_sources(&m["preview"])?;
        Ok(Self {
            id: id.into(),
            preview: m["preview"].clone(),
            sealed: Some(dir.join("report.zip.age")),
            dir,
            lock: Some(lock),
            remote_resolved: false,
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
            if p.join("description.json").try_exists().unwrap_or(true) {
                return Err("REPORT_RECONCILIATION_REQUIRED".into());
            }
            if let Ok(lock) = OpenOptions::new()
                .read(true)
                .write(true)
                .open(p.join("owner.lock"))
            {
                if lock.try_lock_exclusive().is_ok() {
                    let durable = p.join("sealed.json").try_exists().unwrap_or(true)
                        || p.join("draft.json").try_exists().unwrap_or(true)
                        || p.join("description.json").try_exists().unwrap_or(true);
                    let _ = FileExt::unlock(&lock);
                    drop(lock);
                    if !durable {
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
            remote_resolved: false,
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
            let exported=evidence(&report.dir.join("evidence")).unwrap_or_else(|_|json!({"files":[{"name":"events.jsonl","status":"UNAVAILABLE","reason":"RAW_EVENT_SOURCE_UNAVAILABLE"}]}));
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
                "evidence/events.jsonl",
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
            if path == "evidence/events.jsonl" {
                let text = std::str::from_utf8(&bytes).map_err(|_| "INVALID_EVENT_JSONL")?;
                if !text.is_empty() && !text.ends_with('\n') {
                    return Err("TRUNCATED_EVENT_JSONL".into());
                }
                for line in text.lines() {
                    let event: Value =
                        serde_json::from_str(line).map_err(|_| "INVALID_EVENT_JSONL")?;
                    if !event.is_object() {
                        return Err("INVALID_EVENT_JSONL".into());
                    }
                }
            }
            item["bytes"] = json!(bytes.len());
            item["sha256"] = json!(hash(&bytes));
            item["status"] = json!("BEST_EFFORT");
        }
        report.preview = json!({"schemaVersion":"d4planner-issue-report/v1","reportId":report.id,"runId":run,"timestamp":d4planner_runtime_logging::now(),"productVersion":source["productVersion"].take(),"sourceVersion":source["sourceVersion"].take(),"consent":selection,"files":files,"bytes":total,"completeness":if total==0{"EMPTY"}else{"BEST_EFFORT"}});
        validate_sources(&report.preview)?;
        report.save_draft(None)?;
        Ok(report)
    }
    pub fn encrypt(&mut self, config: &Config) -> Result<Value> {
        config.validate()?;
        validate_sources(&self.preview)?;
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
            let mut metadata_file = create(&self.dir.join("sealed.json"))?;
            metadata_file
                .write_all(&serde_json::to_vec(&metadata).map_err(error)?)
                .map_err(error)?;
            metadata_file.sync_all().map_err(error)?;
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
        // Retry cleanup too if a local failure interrupted it after sealing.
        for name in ["logs", "evidence"] {
            let path = self.dir.join(name);
            if !safe(&path) {
                return Err("UNSAFE_PATH".into());
            }
            if path.exists() {
                fs::remove_dir_all(path).map_err(error)?;
            }
        }
        Ok(json!({"reportId":self.id,"sha256":hash(&bytes),"bytes":bytes.len()}))
    }
    fn save_draft(&self, description: Option<&Description>) -> Result<()> {
        let path = self.dir.join("draft.json");
        let next = self.dir.join("draft.next");
        if !safe(&path) || !safe(&next) {
            return Err("UNSAFE_PATH".into());
        }
        let mut value = json!({"schemaVersion":"d4planner-local-draft/v1","preview":self.preview});
        if let Some(d) = description {
            value["description"] = json!(d);
        }
        if next.exists() {
            fs::remove_file(&next).map_err(error)?;
        }
        let mut file = create(&next)?;
        file.write_all(&serde_json::to_vec(&value).map_err(error)?)
            .map_err(error)?;
        file.sync_all().map_err(error)?;
        drop(file);
        fs::rename(next, path).map_err(error)
    }
    fn remember_description(&self, description: &Description) -> Result<()> {
        if serde_json::to_vec(description).map_err(error)?.len() > 30_000 {
            return Err("INVALID_FORM".into());
        }
        if self.pending_remote() {
            if fs::read(self.dir.join("description.json")).map_err(error)?
                != serde_json::to_vec(description).map_err(error)?
            {
                return Err("SUBMITTED_DRAFT_IMMUTABLE".into());
            }
            return Ok(());
        }
        self.save_draft(Some(description))
    }
    fn prepare_submission(
        &mut self,
        config: &Config,
        description: &Description,
        consent: bool,
    ) -> Result<Value> {
        self.remember_description(description)?;
        description.validate()?;
        if !consent {
            return Err("CONSENT_REQUIRED".into());
        }
        self.encrypt(config)
    }
    fn mark_remote_intent(&self, description: &Description) -> Result<()> {
        let path = self.dir.join("description.json");
        if !safe(&path) {
            return Err("UNSAFE_PATH".into());
        }
        let bytes = serde_json::to_vec(description).map_err(error)?;
        if path.exists() {
            if fs::read(path).map_err(error)? != bytes {
                return Err("SUBMITTED_DRAFT_IMMUTABLE".into());
            }
        } else {
            let mut file = create(&path)?;
            file.write_all(&bytes).map_err(error)?;
            file.sync_all().map_err(error)?;
        }
        Ok(())
    }
    /// Native preflight and submission share authoritative persisted state.
    pub fn attempt(
        &mut self,
        config: Result<Config>,
        token: Result<String>,
        description: &Description,
        consent: bool,
    ) -> std::result::Result<Value, SubmissionFailure> {
        let result = (|| {
            self.remember_description(description)?;
            description.validate()?;
            if !consent {
                return Err("CONSENT_REQUIRED".into());
            }
            let token = token?;
            if token.trim().is_empty() {
                return Err("AUTHENTICATION_REQUIRED".into());
            }
            self.submit(&config?, description, &token, consent)
        })();
        result.map_err(|code| SubmissionFailure::for_report(code, self))
    }

    fn accept_response(&mut self, value: Value) -> Result<Value> {
        validate_outcome(&value, &self.id)?;
        self.remote_resolved = true;
        Ok(value)
    }
    pub fn submit(
        &mut self,
        config: &Config,
        description: &Description,
        access_token: &str,
        consent: bool,
    ) -> Result<Value> {
        self.submit_using(
            config,
            description,
            access_token,
            consent,
            |client, request| {
                let response = client.execute(request).map_err(|_| "GATEWAY_OFFLINE")?;
                let status = response.status().as_u16();
                let mut bytes = Vec::new();
                response
                    .take(65_537)
                    .read_to_end(&mut bytes)
                    .map_err(error)?;
                if bytes.len() > 65_536 {
                    return Err("INVALID_GATEWAY_RESPONSE".into());
                }
                Ok((status, bytes))
            },
        )
    }
    fn submit_using(
        &mut self,
        config: &Config,
        description: &Description,
        access_token: &str,
        consent: bool,
        mut exchange: impl FnMut(
            &reqwest::blocking::Client,
            reqwest::blocking::Request,
        ) -> Result<(u16, Vec<u8>)>,
    ) -> Result<Value> {
        if access_token.trim().is_empty() {
            return Err("AUTHENTICATION_REQUIRED".into());
        }
        let artifact = self.prepare_submission(config, description, consent)?;
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .map_err(error)?;
        let endpoint = format!(
            "{}/reports/{}",
            config.gateway.trim_end_matches('/'),
            self.id
        );
        let put = client
            .put(&endpoint)
            .bearer_auth(access_token)
            .json(&json!({"description":description,"artifact":artifact}))
            .build()
            .map_err(error)?;
        let post = client
            .post(format!("{endpoint}/asset"))
            .bearer_auth(access_token)
            .header("Content-Type", "application/octet-stream")
            .body(fs::read(self.sealed.as_ref().unwrap()).map_err(error)?)
            .build()
            .map_err(error)?;
        // All fallible local preparation finishes first. Persist intent before handing
        // any request to transport; every later error remains uncertain until verified terminal.
        self.mark_remote_intent(description)?;
        let (status, bytes) = exchange(&client, put)?;
        if !(200..300).contains(&status) {
            return Err(gateway_failure(status, &bytes));
        }
        let (status, bytes) = exchange(&client, post)?;
        if !(200..300).contains(&status) {
            return Err(gateway_failure(status, &bytes));
        }
        self.accept_response(
            serde_json::from_slice(&bytes).map_err(|_| "INVALID_GATEWAY_RESPONSE")?,
        )
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
        resumed.discard().unwrap();
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
        r.discard().unwrap();
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
        r.discard().unwrap();
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
        r.discard().unwrap();
        fs::remove_file(logs.join("fe.log")).unwrap();
        let r = Report::collect(&p, &s.id, selected(), |_| panic!()).unwrap();
        assert_eq!(r.preview["files"][0]["status"], "UNAVAILABLE");
        r.discard().unwrap();
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
        r.discard().unwrap();
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
            fs::write(dest.join("events.jsonl"), b"{\"partial\":").unwrap();
            Err("EVIDENCE_TIMEOUT".into())
        })
        .unwrap();
        assert_eq!(r.preview["files"][0]["status"], "UNAVAILABLE");
        assert_eq!(r.preview["bytes"], 0);
        r.discard().unwrap();
        fs::remove_dir_all(data).unwrap();
    }
}

// Shared by collection, encryption and persisted-draft recovery. Old DB-bearing
// drafts are rejected, never silently uploaded after the attachment contract changed.
fn validate_sources(preview: &Value) -> Result<()> {
    let files = preview["files"].as_array().ok_or("INVALID_EXPORT")?;
    let mut seen = std::collections::HashSet::new();
    for file in files {
        let path = file["path"].as_str().ok_or("INVALID_EXPORT")?;
        let selected = match path {
            "logs/fe.log" => preview["consent"]["fe"] == true,
            "logs/be.log" => preview["consent"]["be"] == true,
            "logs/rulekit.log" => preview["consent"]["rulekit"] == true,
            "evidence/events.jsonl" => {
                preview["consent"]["evidence"] == true
                    && preview["consent"]["evidenceConsent"] == true
            }
            _ => false,
        };
        if !selected || !seen.insert(path) {
            return Err("INVALID_EXPORT_SOURCE".into());
        }
    }
    Ok(())
}

#[cfg(test)]
mod raw_event_contract_tests {
    use super::*;
    #[test]
    fn rejects_forbidden_sources_even_in_old_drafts() {
        for name in [
            "events.db",
            "character.db",
            "events.db-wal",
            "equipment-projector.jsonl",
            "raw-speech.jsonl",
        ] {
            let preview = json!({"consent":{"evidence":true,"evidenceConsent":true},"files":[{"path":format!("evidence/{name}")}]});
            assert!(validate_sources(&preview).is_err(), "{name}");
        }
    }
    #[test]
    fn raw_jsonl_validation_and_exact_four_source_allowlist() {
        for (bytes, valid) in [
            (b"{\"sessionId\":\"synthetic\"}\n".as_slice(), true),
            (b"{\"partial\":".as_slice(), false),
            (b"invalid\n".as_slice(), false),
            (b"[]\n".as_slice(), false),
        ] {
            let data = std::env::temp_dir().join(format!("raw-event-{}", uuid::Uuid::new_v4()));
            fs::create_dir(&data).unwrap();
            let selection = Selection {
                fe: false,
                be: false,
                rulekit: false,
                evidence: true,
                evidence_consent: true,
            };
            let result = Report::collect(&data, "synthetic", selection, |dest| {
                fs::create_dir(dest).unwrap();
                fs::write(dest.join("events.jsonl"), bytes).unwrap();
                Ok(
                    json!({"files":[{"name":"events.jsonl","status":"BEST_EFFORT","sessionId":"synthetic"}]}),
                )
            });
            assert_eq!(result.is_ok(), valid);
            if let Ok(report) = result {
                assert_eq!(report.preview["files"].as_array().unwrap().len(), 1);
                assert_eq!(
                    fs::read(report.dir.join("evidence/events.jsonl")).unwrap(),
                    bytes
                );
                report.discard().unwrap();
            }
            fs::remove_dir_all(data).unwrap();
        }
    }
}

#[cfg(test)]
mod pending_review_tests {
    use super::*;
    #[test]
    fn cancel_cannot_destroy_a_remote_uncertain_report() {
        let data = std::env::temp_dir().join(format!("pending-review-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&data).unwrap();
        let mut r = Report::collect(
            &data,
            "no-logs",
            Selection {
                fe: false,
                be: false,
                rulekit: false,
                evidence: false,
                evidence_consent: false,
            },
            |_| panic!(),
        )
        .unwrap();
        let config = Config {
            recipient: age::x25519::Identity::generate().to_public().to_string(),
            gateway: "https://example.invalid".into(),
            max_bytes: MAX,
        };
        r.encrypt(&config).unwrap();
        let dir = r.dir.clone();
        fs::write(dir.join("description.json"), b"{}").unwrap();
        let before = fs::read(dir.join("report.zip.age")).unwrap();
        let _ = r.discard();
        assert_eq!(fs::read(dir.join("report.zip.age")).unwrap(), before);
        fs::remove_dir_all(data).unwrap();
    }
}

fn validate_outcome(value: &Value, id: &str) -> Result<()> {
    let url = value["issueUrl"]
        .as_str()
        .ok_or("INVALID_GATEWAY_RESPONSE")?;
    let number = url
        .strip_prefix("https://github.com/Synclab-VN-dev/StreamOps/issues/")
        .ok_or("INVALID_GATEWAY_RESPONSE")?;
    if number.is_empty()
        || !number.bytes().all(|b| b.is_ascii_digit())
        || number.parse::<u64>().unwrap_or(0) == 0
        || value["reportId"] != id
    {
        return Err("INVALID_GATEWAY_RESPONSE".into());
    }
    match value["status"].as_str() {
        Some("COMPLETE" | "EXPIRED") => Ok(()),
        Some("PENDING" | "UPLOAD_PENDING" | "LOG_UPLOAD_PENDING" | "ERROR") => {
            Err("UPLOAD_PENDING".into())
        }
        _ => Err("INVALID_GATEWAY_RESPONSE".into()),
    }
}

#[cfg(test)]
mod outcome_review_tests {
    use super::*;
    fn selection() -> Selection {
        Selection {
            fe: false,
            be: false,
            rulekit: false,
            evidence: false,
            evidence_consent: false,
        }
    }
    #[test]
    fn uncertain_submission_restart_recollect_cancel_and_terminal_reconciliation() {
        for status in ["COMPLETE", "EXPIRED"] {
            let data = std::env::temp_dir().join(format!("retry-review-{}", uuid::Uuid::new_v4()));
            fs::create_dir(&data).unwrap();
            let mut r = Report::collect(&data, "no-logs", selection(), |_| panic!()).unwrap();
            let config = Config {
                recipient: age::x25519::Identity::generate().to_public().to_string(),
                gateway: "https://example.invalid".into(),
                max_bytes: MAX,
            };
            let description = Description {
                issue_type: "Other".into(),
                title: "synthetic".into(),
                actual: "offline".into(),
                expected: "retry".into(),
                steps: "".into(),
            };
            let artifact = r.prepare_submission(&config, &description, true).unwrap();
            let id = r.id.clone();
            let dir = r.dir.clone();
            let ciphertext = fs::read(dir.join("report.zip.age")).unwrap();
            r.mark_remote_intent(&description).unwrap();
            // Network loss after PUT or POST: no terminal response reached client.
            assert!(r.pending_remote());
            drop(r); // application restart releases only lock, not ciphertext
            assert!(Report::collect(&data, "no-logs", selection(), |_| panic!()).is_err());
            let r = Report::resume(&data, &id).unwrap();
            assert_eq!(r.restored_preview()["pendingRemote"], true);
            assert_eq!(r.restored_preview()["description"]["title"], "synthetic");
            assert!(r.discard().is_err());
            let mut r = Report::resume(&data, &id).unwrap();
            assert_eq!(
                r.prepare_submission(&config, &description, true).unwrap(),
                artifact
            );
            assert_eq!(fs::read(dir.join("report.zip.age")).unwrap(), ciphertext);
            for response in [
                json!({"status":"UPLOAD_PENDING"}),
                json!({"status":"UNKNOWN"}),
                json!({"status":"COMPLETE","reportId":"foreign"}),
            ] {
                assert!(r.accept_response(response).is_err());
                assert!(r.pending_remote());
            }
            r.accept_response(json!({"status":status,"reportId":id,"issueUrl":"https://github.com/Synclab-VN-dev/StreamOps/issues/123"})).unwrap();
            assert!(!r.pending_remote());
            r.discard().unwrap();
            assert!(!dir.exists());
            let draft = Report::collect(&data, "no-logs", selection(), |_| panic!()).unwrap();
            let dir = draft.dir.clone();
            draft.discard().unwrap();
            assert!(!dir.exists());
            fs::remove_dir_all(data).unwrap();
        }
    }
    #[test]
    fn outcome_contract_requires_terminal_status_identity_and_valid_issue_url() {
        for status in [
            "COMPLETE",
            "EXPIRED",
            "UPLOAD_PENDING",
            "PENDING",
            "ERROR",
            "UNKNOWN",
        ] {
            let value = json!({"status":status,"reportId":"same","issueUrl":"https://github.com/Synclab-VN-dev/StreamOps/issues/123"});
            assert_eq!(
                validate_outcome(&value, "same").is_ok(),
                matches!(status, "COMPLETE" | "EXPIRED")
            );
            assert!(validate_outcome(&value, "different").is_err());
        }
        for suffix in ["", "0", "../123", "123?token=private"] {
            assert!(validate_outcome(&json!({"status":"COMPLETE","reportId":"same","issueUrl":format!("https://github.com/Synclab-VN-dev/StreamOps/issues/{suffix}")}),"same").is_err());
        }
    }
}

#[cfg(test)]
mod local_recovery_tests {
    use super::*;
    fn draft() -> (PathBuf, Report, Config, Description) {
        let data = std::env::temp_dir().join(format!("f162-01-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&data).unwrap();
        let r = Report::collect(
            &data,
            "no-logs",
            Selection {
                fe: false,
                be: false,
                rulekit: false,
                evidence: false,
                evidence_consent: false,
            },
            |_| panic!(),
        )
        .unwrap();
        let c = Config {
            recipient: age::x25519::Identity::generate().to_public().to_string(),
            gateway: "https://example.invalid".into(),
            max_bytes: MAX,
        };
        let d = Description {
            issue_type: "Other".into(),
            title: "local draft".into(),
            actual: "failure".into(),
            expected: "recover".into(),
            steps: "".into(),
        };
        (data, r, c, d)
    }
    #[test]
    fn unsealed_collection_survives_restart_and_can_be_discarded() {
        let (data, r, _, _) = draft();
        let id = r.id.clone();
        let preview = r.preview.clone();
        drop(r);
        let restored = Report::resume(&data, &id).expect("durable unsealed collection");
        assert_eq!(restored.preview, preview);
        assert!(!restored.pending_remote());
        restored.discard().unwrap();
        fs::remove_dir_all(data).unwrap();
    }
    #[test]
    fn encryption_preparation_is_not_remote_intent() {
        let (data, mut r, c, d) = draft();
        r.prepare_submission(&c, &d, true).unwrap();
        assert!(!r.pending_remote(), "no HTTP was attempted");
        r.discard().unwrap();
        fs::remove_dir_all(data).unwrap();
    }
}

#[cfg(test)]
mod submission_boundary_tests {
    use super::*;
    fn fixture() -> (PathBuf, Report, Config, Description) {
        let data = std::env::temp_dir().join(format!("f162-boundary-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&data).unwrap();
        let r = Report::collect(
            &data,
            "no-logs",
            Selection {
                fe: false,
                be: false,
                rulekit: false,
                evidence: false,
                evidence_consent: false,
            },
            |_| panic!(),
        )
        .unwrap();
        (
            data,
            r,
            Config {
                recipient: age::x25519::Identity::generate().to_public().to_string(),
                gateway: "https://example.invalid".into(),
                max_bytes: MAX,
            },
            Description {
                issue_type: "Other".into(),
                title: "persist me".into(),
                actual: "failure".into(),
                expected: "recover".into(),
                steps: "user steps".into(),
            },
        )
    }
    #[test]
    fn preflight_errors_remain_local_and_restore_form_after_restart() {
        for case in [
            "token",
            "config-file",
            "config",
            "consent",
            "form",
            "encryption",
        ] {
            let (data, mut r, mut c, mut d) = fixture();
            let id = r.id.clone();
            let dir = r.dir.clone();
            if case == "config" {
                c.gateway = "http://forbidden.invalid".into();
            }
            if case == "form" {
                d.title = "".into();
            }
            if case == "encryption" {
                c.max_bytes = 1;
            }
            let config = if case == "config-file" {
                Err("REPORT_NOT_CONFIGURED".into())
            } else {
                Ok(c)
            };
            let token = if case == "token" {
                Err("AUTHENTICATION_REQUIRED".into())
            } else {
                Ok("synthetic".into())
            };
            let err = r.attempt(config, token, &d, case != "consent").unwrap_err();
            assert_eq!(err.state, "LOCAL_FAILURE", "{case}");
            assert!(!dir.join("description.json").exists());
            assert!(!r.pending_remote());
            drop(r);
            let restored = Report::resume(&data, &id).unwrap();
            assert_eq!(restored.restored_preview()["description"], json!(d));
            assert_eq!(restored.restored_preview()["pendingRemote"], false);
            restored.discard().unwrap();
            assert!(!dir.exists());
            fs::remove_dir_all(data).unwrap();
        }
    }
    #[test]
    fn zip_failure_never_reaches_transport_and_is_retryable() {
        let (data, mut r, c, d) = fixture();
        let dir = r.dir.clone();
        fs::create_dir(dir.join("report.zip")).unwrap();
        let result = r.submit_using(&c, &d, "synthetic", true, |_, _| {
            panic!("no HTTP before ZIP success")
        });
        assert!(result.is_err());
        assert!(!r.pending_remote());
        fs::remove_dir(dir.join("report.zip")).unwrap();
        let id = r.id.clone();
        drop(r);
        let mut r = Report::resume(&data, &id).unwrap();
        r.prepare_submission(&c, &d, true).unwrap();
        assert!(!r.pending_remote());
        r.discard().unwrap();
        fs::remove_dir_all(data).unwrap();
    }
    #[test]
    fn put_post_loss_http_errors_and_nonterminal_responses_preserve_identity() {
        for case in [
            "PUT_LOSS",
            "POST_LOSS",
            "HTTP_401",
            "PENDING",
            "UNKNOWN",
            "MALFORMED",
            "WRONG_ID",
        ] {
            let (data, mut r, c, d) = fixture();
            let id = r.id.clone();
            let dir = r.dir.clone();
            let mut calls = 0;
            let result=r.submit_using(&c,&d,"synthetic",true,|_,req| {
                calls+=1;
                assert_eq!(req.url().scheme(),"https");
                if calls==1 {
                    assert_eq!(req.method(),reqwest::Method::PUT);
                    if case=="PUT_LOSS" {return Err("LOST_RESPONSE".into());}
                    if case=="HTTP_401" {return Ok((401,vec![]));}
                    return Ok((200,b"{}".to_vec()));
                }
                assert_eq!(req.method(),reqwest::Method::POST);
                assert!(req.body().unwrap().as_bytes().unwrap().starts_with(b"age-encryption.org/v1"));
                if case=="POST_LOSS" {return Err("LOST_RESPONSE".into());}
                let value=if case=="MALFORMED" {b"broken".to_vec()}else{
                    serde_json::to_vec(&json!({"status":case,"reportId":if case=="WRONG_ID"{"foreign"}else{&id},"issueUrl":"https://github.com/Synclab-VN-dev/StreamOps/issues/123"})).unwrap()
                };Ok((200,value))
            });
            assert!(result.is_err(), "{case}");
            assert!(r.pending_remote());
            let ciphertext = fs::read(dir.join("report.zip.age")).unwrap();
            drop(r);
            let mut r = Report::resume(&data, &id).unwrap();
            let err = r
                .attempt(
                    Err("REPORT_NOT_CONFIGURED".into()),
                    Err("AUTHENTICATION_REQUIRED".into()),
                    &d,
                    true,
                )
                .unwrap_err();
            assert_eq!(
                err.state, "REMOTE_OUTCOME_UNCERTAIN",
                "auth failure must not downgrade previous send"
            );
            assert!(r.discard().is_err());
            assert_eq!(fs::read(dir.join("report.zip.age")).unwrap(), ciphertext);
            let mut r = Report::resume(&data, &id).unwrap();
            let mut calls = 0;
            r.submit_using(&c,&d,"synthetic",true,|_,req| {
                calls+=1;
                if calls==1 {
                    let body:Value=serde_json::from_slice(req.body().unwrap().as_bytes().unwrap()).unwrap();
                    assert_eq!(body["artifact"]["reportId"],id);assert_eq!(body["artifact"]["sha256"],hash(&ciphertext));
                    assert_eq!(body["description"],json!(d));return Ok((200,b"{}".to_vec()));
                }
                assert_eq!(req.body().unwrap().as_bytes().unwrap(),ciphertext);
                Ok((200,serde_json::to_vec(&json!({"status":"COMPLETE","reportId":id,"issueUrl":"https://github.com/Synclab-VN-dev/StreamOps/issues/123"})).unwrap()))
            }).unwrap();
            assert!(!r.pending_remote());
            r.discard().unwrap();
            assert!(!dir.exists());
            fs::remove_dir_all(data).unwrap();
        }
    }
    #[test]
    fn corrupt_local_or_remote_draft_cannot_be_downgraded_or_reclaimed() {
        let (data, mut r, c, d) = fixture();
        let id = r.id.clone();
        let dir = r.dir.clone();
        r.prepare_submission(&c, &d, true).unwrap();
        r.mark_remote_intent(&d).unwrap();
        drop(r);
        fs::remove_file(dir.join("sealed.json")).unwrap();
        assert!(Report::resume(&data, &id).is_err());
        assert!(Report::collect(
            &data,
            "no-logs",
            Selection {
                fe: false,
                be: false,
                rulekit: false,
                evidence: false,
                evidence_consent: false
            },
            |_| panic!()
        )
        .is_err());
        assert!(dir.join("report.zip.age").is_file());
        fs::remove_dir_all(data).unwrap();
        let (data, r, _, _) = fixture();
        let id = r.id.clone();
        let dir = r.dir.clone();
        drop(r);
        let mut draft: Value =
            serde_json::from_slice(&fs::read(dir.join("draft.json")).unwrap()).unwrap();
        draft["description"] = json!({"title":42});
        fs::write(dir.join("draft.json"), serde_json::to_vec(&draft).unwrap()).unwrap();
        assert!(Report::resume(&data, &id).is_err());
        fs::write(dir.join("draft.json"), b"corrupt").unwrap();
        assert!(Report::resume(&data, &id).is_err());
        assert!(dir.exists());
        fs::remove_dir_all(data).unwrap();
    }
}

#[cfg(test)]
mod process_recovery_tests {
    use super::*;
    #[test]
    fn child_checkpoint() {
        let Some(data) = std::env::var_os("F162_CHILD_DATA") else {
            return;
        };
        let data = PathBuf::from(data);
        let run = std::env::var("F162_CHILD_RUN").unwrap();
        let mut r = Report::collect(
            &data,
            &run,
            Selection {
                fe: true,
                be: false,
                rulekit: false,
                evidence: false,
                evidence_consent: false,
            },
            |_| panic!(),
        )
        .unwrap();
        let d = Description {
            issue_type: "Other".into(),
            title: "process restart".into(),
            actual: "local or network loss".into(),
            expected: "recover".into(),
            steps: "".into(),
        };
        let c = Config {
            recipient: age::x25519::Identity::generate().to_public().to_string(),
            gateway: "https://example.invalid".into(),
            max_bytes: MAX,
        };
        if std::env::var("F162_CHILD_MODE").unwrap() == "remote" {
            assert!(r
                .submit_using(&c, &d, "synthetic", true, |_, request| {
                    assert_eq!(request.method(), reqwest::Method::PUT);
                    Err("LOST_PUT_RESPONSE".into())
                })
                .is_err());
        } else {
            assert_eq!(
                r.attempt(Ok(c), Err("AUTHENTICATION_REQUIRED".into()), &d, true)
                    .unwrap_err()
                    .state,
                "LOCAL_FAILURE"
            );
        }
        fs::write(
            data.join("checkpoint.json"),
            serde_json::to_vec(&json!({"id":r.id,"preview":r.preview})).unwrap(),
        )
        .unwrap();
        // No Report Drop: exercise OS lock release and on-disk recovery after process exit.
        std::process::exit(0);
    }
    #[test]
    fn process_exit_restores_selected_files_local_form_and_remote_intent() {
        for mode in ["local", "remote"] {
            let data = std::env::temp_dir().join(format!("f162-process-{}", uuid::Uuid::new_v4()));
            fs::create_dir(&data).unwrap();
            let session = d4planner_runtime_logging::Session::create(&data, "1", "test").unwrap();
            let source = fs::read(session.dir.join("fe.log")).unwrap();
            let out = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "process_recovery_tests::child_checkpoint",
                    "--nocapture",
                ])
                .env("F162_CHILD_DATA", &data)
                .env("F162_CHILD_RUN", &session.id)
                .env("F162_CHILD_MODE", mode)
                .output()
                .unwrap();
            assert!(
                out.status.success(),
                "{}",
                String::from_utf8_lossy(&out.stderr)
            );
            assert_eq!(fs::read(session.dir.join("fe.log")).unwrap(), source);
            let checkpoint: Value =
                serde_json::from_slice(&fs::read(data.join("checkpoint.json")).unwrap()).unwrap();
            let r = Report::resume(&data, checkpoint["id"].as_str().unwrap()).unwrap();
            assert_eq!(r.preview, checkpoint["preview"]);
            assert_eq!(
                r.restored_preview()["description"]["title"],
                "process restart"
            );
            assert_eq!(r.pending_remote(), mode == "remote");
            if mode == "remote" {
                assert!(r.discard().is_err());
            } else {
                r.discard().unwrap();
            }
            drop(session);
            fs::remove_dir_all(data).unwrap();
        }
    }
}

#[cfg(test)]
mod gateway_failure_tests {
    #[test]
    fn actionable_codes_are_allowlisted_and_response_text_is_not_exposed() {
        assert_eq!(
            super::gateway_failure(503, br#"{"error":"GITHUB_403"}"#),
            "GITHUB_403"
        );
        assert_eq!(
            super::gateway_failure(503, br#"{"error":"SECRET_TOKEN"}"#),
            "GATEWAY_503"
        );
    }
}
