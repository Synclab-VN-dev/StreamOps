//! Shared desktop/web draft ownership. Transport credentials and raw logs never
//! enter this index; existing Report remains responsible for collection/submission.
use crate::{Description, Report, Selection, SubmissionFailure};
use serde_json::{json, Value};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};

#[derive(Default)]
pub struct Coordinator {
    active: Option<(String, Report)>,
}
fn receipt_path(root: &Path, id: &str) -> Result<PathBuf, String> {
    if uuid::Uuid::parse_str(id).is_err() {
        return Err("INVALID_REPORT_ID".into());
    }
    let path = root
        .join("private")
        .join("report-access")
        .join(format!("{id}.json"));
    if !d4planner_runtime_logging::safe(&path) {
        return Err("UNSAFE_PATH".into());
    }
    Ok(path)
}
fn access(root: &Path, id: &str, actor: &str) -> Result<Value, String> {
    let path = receipt_path(root, id)?;
    if !path.exists() {
        return if actor == "desktop" {
            Ok(json!({"actor":"desktop"}))
        } else {
            Err("REPORT_NOT_FOUND".into())
        };
    }
    if fs::metadata(&path).map_err(|_| "REPORT_NOT_FOUND")?.len() > 16384 {
        return Err("INVALID_REPORT".into());
    }
    let mut value: Value =
        serde_json::from_slice(&fs::read(&path).map_err(|_| "REPORT_NOT_FOUND")?)
            .map_err(|_| "INVALID_REPORT")?;
    if value["actor"] != actor {
        return Err("REPORT_NOT_FOUND".into());
    }
    let terminal = path.with_extension("result.json");
    if !d4planner_runtime_logging::safe(&terminal) {
        return Err("UNSAFE_PATH".into());
    }
    if terminal.exists() {
        if fs::metadata(&terminal).map_err(|_| "INVALID_REPORT")?.len() > 16384 {
            return Err("INVALID_REPORT".into());
        }
        let result: Value =
            serde_json::from_slice(&fs::read(terminal).map_err(|_| "INVALID_REPORT")?)
                .map_err(|_| "INVALID_REPORT")?;
        if result["actor"] != actor {
            return Err("REPORT_NOT_FOUND".into());
        }
        crate::validate_outcome(&result["result"], id)?;
        value = result;
    }
    Ok(value)
}
fn store(root: &Path, id: &str, value: &Value) -> Result<(), String> {
    let base = receipt_path(root, id)?;
    let path = if value.get("result").is_some() {
        base.with_extension("result.json")
    } else {
        base
    };
    let directory = path.parent().ok_or("UNSAFE_PATH")?;
    crate::private_dir(directory)?;
    // Bound terminal receipt metadata. Never remove a nonterminal draft/access record.
    for item in fs::read_dir(directory).map_err(|_| "REPORT_STORAGE_FAILED")? {
        let item = item.map_err(|_| "REPORT_STORAGE_FAILED")?;
        let p = item.path();
        if !d4planner_runtime_logging::safe(&p) {
            return Err("UNSAFE_PATH".into());
        }
        if !p.exists() {
            continue;
        }
        let meta = item.metadata().map_err(|_| "REPORT_STORAGE_FAILED")?;
        if meta.len() <= 16384
            && meta
                .modified()
                .ok()
                .and_then(|t| t.elapsed().ok())
                .is_some_and(|d| d.as_secs() > 7 * 86400)
        {
            if let Ok(v) = fs::read(&p)
                .and_then(|b| serde_json::from_slice::<Value>(&b).map_err(std::io::Error::other))
            {
                if v.get("result").is_some() {
                    fs::remove_file(&p).map_err(|_| "REPORT_STORAGE_FAILED")?;
                    if let Some(name) = p
                        .file_name()
                        .and_then(|n| n.to_str())
                        .and_then(|n| n.strip_suffix(".result.json"))
                    {
                        if uuid::Uuid::parse_str(name).is_ok() {
                            let _ = fs::remove_file(directory.join(format!("{name}.json")));
                        }
                    }
                }
            }
        }
    }
    let count = fs::read_dir(directory)
        .map_err(|_| "REPORT_STORAGE_FAILED")?
        .count();
    if count >= 128 && !path.exists() {
        return Err("REPORT_RETENTION_LIMIT".into());
    }
    let next = path.with_extension(format!("{}.next", uuid::Uuid::new_v4()));
    if !d4planner_runtime_logging::safe(&next) {
        return Err("UNSAFE_PATH".into());
    }
    let bytes = serde_json::to_vec(value).map_err(|_| "REPORT_STORAGE_FAILED")?;
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&next).map_err(|_| "REPORT_STORAGE_FAILED")?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| "REPORT_STORAGE_FAILED")?;
    if path.exists() {
        let old = fs::read(&path).map_err(|_| "REPORT_STORAGE_FAILED")?;
        let _ = fs::remove_file(&next);
        return if old == bytes {
            Ok(())
        } else {
            Err("REPORT_RECEIPT_CONFLICT".into())
        };
    }
    fs::rename(next, path).map_err(|_| "REPORT_STORAGE_FAILED")?;
    Ok(())
}
impl Coordinator {
    pub const fn new() -> Self {
        Self { active: None }
    }
    pub fn collect(
        &mut self,
        root: &Path,
        run: &str,
        actor: &str,
        selection: Selection,
        evidence: impl FnOnce(&Path) -> Result<Value, String>,
    ) -> Result<Value, String> {
        if let Some((owner, report)) = &self.active {
            if owner != actor {
                return Err("REPORT_BUSY".into());
            }
            if report.pending_remote() {
                return Err("REPORT_RECONCILIATION_REQUIRED".into());
            }
        }
        if let Some((_, old)) = self.active.take() {
            let id = old.id.clone();
            old.discard()?;
            let _ = fs::remove_file(receipt_path(root, &id)?);
        }
        let report = Report::collect(root, run, selection, evidence)?;
        if let Err(error) = store(root, &report.id, &json!({"actor":actor})) {
            let _ = report.discard();
            return Err(error);
        }
        let preview = report.preview.clone();
        self.active = Some((actor.into(), report));
        Ok(preview)
    }
    pub fn status(&mut self, root: &Path, actor: &str, id: &str) -> Result<Value, String> {
        let record = access(root, id, actor)?;
        if let Some(result) = record.get("result") {
            return Ok(result.clone());
        }
        if self
            .active
            .as_ref()
            .is_some_and(|(a, r)| a != actor || r.id != id)
        {
            return Err("REPORT_BUSY".into());
        }
        if self.active.is_none() {
            self.active = Some((actor.into(), Report::resume(root, id)?));
        }
        Ok(self
            .active
            .as_ref()
            .ok_or("REPORT_NOT_FOUND")?
            .1
            .restored_preview())
    }
    pub fn cancel(&mut self, root: &Path, actor: &str, id: Option<&str>) -> Result<(), String> {
        let id = id
            .map(str::to_owned)
            .or_else(|| {
                self.active
                    .as_ref()
                    .filter(|(a, _)| a == actor)
                    .map(|(_, r)| r.id.clone())
            })
            .ok_or("REPORT_NOT_COLLECTED")?;
        let status = self.status(root, actor, &id)?;
        if status.get("issueUrl").is_some() {
            return Err("REPORT_ALREADY_SUBMITTED".into());
        }
        let report = &self.active.as_ref().ok_or("REPORT_NOT_COLLECTED")?.1;
        if report.pending_remote() {
            return Err("REPORT_RECONCILIATION_REQUIRED".into());
        }
        let (_, report) = self.active.take().ok_or("REPORT_NOT_COLLECTED")?;
        report.discard()?;
        fs::remove_file(receipt_path(root, &id)?)
            .or_else(|e| {
                if e.kind() == std::io::ErrorKind::NotFound {
                    Ok(())
                } else {
                    Err(e)
                }
            })
            .map_err(|_| "REPORT_STORAGE_FAILED")?;
        Ok(())
    }
    pub fn submit(
        &mut self,
        root: &Path,
        actor: &str,
        id: &str,
        description: Description,
        consent: bool,
        attempt: impl FnOnce(&mut Report, &Description, bool) -> Result<Value, SubmissionFailure>,
    ) -> Result<Value, SubmissionFailure> {
        let preview = self
            .status(root, actor, id)
            .map_err(SubmissionFailure::uncertain)?;
        if preview.get("issueUrl").is_some() {
            return Ok(preview);
        }
        let (_, report) = self
            .active
            .as_mut()
            .ok_or_else(|| SubmissionFailure::uncertain("REPORT_NOT_COLLECTED"))?;
        let result = attempt(report, &description, consent)?;
        crate::validate_outcome(&result, id).map_err(SubmissionFailure::uncertain)?;
        store(root, id, &json!({"actor":actor,"result":result}))
            .map_err(SubmissionFailure::uncertain)?;
        if let Some((_, report)) = self.active.take() {
            report.discard().map_err(SubmissionFailure::uncertain)?;
        }
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
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
    fn root() -> PathBuf {
        let root = std::env::temp_dir().join(format!("web-report-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        root
    }
    #[test]
    fn cross_actor_cannot_replace_resume_or_cancel_and_restart_preserves_owner() {
        let root = root();
        let mut coordinator = Coordinator::new();
        let preview = coordinator
            .collect(&root, "test-run", "web:alice", selection(), |_| panic!())
            .unwrap();
        let id = preview["reportId"].as_str().unwrap();
        assert_eq!(
            coordinator
                .collect(&root, "test-run", "desktop", selection(), |_| panic!())
                .unwrap_err(),
            "REPORT_BUSY"
        );
        assert_eq!(
            coordinator.status(&root, "web:bob", id).unwrap_err(),
            "REPORT_NOT_FOUND"
        );
        assert_eq!(
            coordinator.cancel(&root, "web:bob", Some(id)).unwrap_err(),
            "REPORT_NOT_FOUND"
        );
        drop(coordinator);
        let mut coordinator = Coordinator::new();
        assert_eq!(
            coordinator.status(&root, "web:alice", id).unwrap()["reportId"],
            id
        );
        coordinator.cancel(&root, "web:alice", Some(id)).unwrap();
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn local_consent_failure_preserves_exact_draft_and_no_transport() {
        let root = root();
        let mut coordinator = Coordinator::new();
        let p = coordinator
            .collect(&root, "test-run", "web:alice", selection(), |_| panic!())
            .unwrap();
        let id = p["reportId"].as_str().unwrap();
        let d = Description {
            issue_type: "Other".into(),
            title: "Test".into(),
            actual: "Test".into(),
            expected: "Test".into(),
            steps: "".into(),
        };
        let error = coordinator
            .submit(&root, "web:alice", id, d, false, |r, d, c| {
                r.attempt(
                    Err("INVALID_REPORT_CONFIG".into()),
                    Err("AUTHENTICATION_REQUIRED".into()),
                    d,
                    c,
                )
            })
            .unwrap_err();
        assert_eq!(error.state, "LOCAL_FAILURE");
        assert_eq!(
            coordinator.status(&root, "web:alice", id).unwrap()["reportId"],
            id
        );
        coordinator.cancel(&root, "web:alice", Some(id)).unwrap();
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn malformed_id_and_tampered_ownership_fail_closed() {
        let root = root();
        let mut coordinator = Coordinator::new();
        assert!(coordinator
            .status(&root, "web:alice", "../../config")
            .is_err());
        let p = coordinator
            .collect(&root, "test-run", "web:alice", selection(), |_| panic!())
            .unwrap();
        let id = p["reportId"].as_str().unwrap();
        fs::write(receipt_path(&root, id).unwrap(), b"corrupt").unwrap();
        assert_eq!(
            coordinator.status(&root, "web:alice", id).unwrap_err(),
            "INVALID_REPORT"
        );
        drop(coordinator);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn terminal_receipt_survives_restart_and_cannot_cancel_a_new_draft() {
        let root = root();
        let mut c = Coordinator::new();
        let first = c
            .collect(&root, "test-run", "web:alice", selection(), |_| panic!())
            .unwrap();
        let id = first["reportId"].as_str().unwrap();
        let description = Description {
            issue_type: "Other".into(),
            title: "Test".into(),
            actual: "a".into(),
            expected: "b".into(),
            steps: "".into(),
        };
        let result=c.submit(&root,"web:alice",id,description.clone(),true,|r,_,_|r.accept_response(json!({"reportId":id,"status":"COMPLETE","issueUrl":"https://github.com/Synclab-VN-dev/StreamOps/issues/201"})).map_err(SubmissionFailure::uncertain)).unwrap();
        drop(c);
        let mut c = Coordinator::new();
        assert_eq!(c.status(&root, "web:alice", id).unwrap(), result);
        assert_eq!(
            c.submit(&root, "web:alice", id, description, true, |_, _, _| panic!(
                "terminal retry must not resubmit"
            ))
            .unwrap(),
            result
        );
        let second = c
            .collect(&root, "test-run", "web:alice", selection(), |_| panic!())
            .unwrap();
        assert_eq!(
            c.cancel(&root, "web:alice", Some(id)).unwrap_err(),
            "REPORT_ALREADY_SUBMITTED"
        );
        c.cancel(&root, "web:alice", second["reportId"].as_str())
            .unwrap();
        fs::remove_dir_all(root).unwrap();
    }
}
