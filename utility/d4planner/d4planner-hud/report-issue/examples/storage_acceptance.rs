//! Encrypt only a selected real run's FE log; never submit to a gateway.
use d4planner_report_issue::{Config, Report, Selection};
use serde_json::json;
use std::{fs, io::Read, path::PathBuf};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 { return Err("usage: storage_acceptance DATA_ROOT RUN_ID REPORT_JSON".into()); }
    let data = PathBuf::from(&args[1]);
    let mut report = Report::collect(&data, &args[2], Selection {
        fe: true, be: false, rulekit: false, evidence: false, evidence_consent: false,
    }, |_| panic!("unselected evidence provider must not execute"))?;
    let identity = age::x25519::Identity::generate();
    let config = Config { recipient: identity.to_public().to_string(), gateway: "https://gateway.invalid".into(), max_bytes: 64_000_000 };
    let sealed_metadata = report.encrypt(&config)?;
    let dir = data.join("private").join(format!("report-{}", report.id));
    let sealed = fs::read(dir.join("report.zip.age"))?;
    let mut plain = Vec::new();
    age::Decryptor::new(&sealed[..])?.decrypt(std::iter::once(&identity as &dyn age::Identity))?.read_to_end(&mut plain)?;
    let mut zip = zip::ZipArchive::new(std::io::Cursor::new(plain))?;
    let names: Vec<_> = (0..zip.len()).map(|i| zip.by_index(i).unwrap().name().to_owned()).collect();
    assert_eq!(names.len(), 2);
    assert!(names.contains(&"manifest.json".to_string()));
    assert!(names.contains(&"logs/fe.log".to_string()));
    let mut log = Vec::new(); zip.by_name("logs/fe.log")?.read_to_end(&mut log)?;
    let runs: Vec<_> = fs::read_dir(data.join("logs"))?.filter_map(Result::ok).filter(|entry| entry.file_name().to_string_lossy().ends_with(&format!("_{}", args[2]))).collect();
    assert_eq!(runs.len(), 1);
    assert_eq!(log, fs::read(runs[0].path().join("fe.log"))?);
    let preview = report.preview.clone(); let id = report.id.clone();
    assert!(!dir.join("report.zip").exists()); assert!(!dir.join("logs").exists());
    drop(report);
    let mut resumed = Report::resume(&data, &id)?;
    assert_eq!(resumed.encrypt(&config)?, sealed_metadata);
    resumed.discard()?; assert!(!dir.exists());
    fs::write(&args[3], serde_json::to_vec_pretty(&json!({"status":"PASS", "runId":args[2], "selected":["fe"], "zipEntries":names, "preview":preview, "encrypted":sealed_metadata, "exactLogBytes":log.len(), "resumeIdentical":true, "discarded":true, "networkSubmission":false}))?)?;
    Ok(())
}
