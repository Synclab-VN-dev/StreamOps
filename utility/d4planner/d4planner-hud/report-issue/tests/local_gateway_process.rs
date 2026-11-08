use d4planner_report_issue::local_gateway::LocalGateway;
use std::{fs, path::PathBuf};

#[test]
#[ignore = "requires D4PLANNER_TEST_PYTHON and backend PYTHONPATH"]
fn real_backend_missing_config_and_invalid_recipient_stop_before_network() {
    let python = PathBuf::from(std::env::var("D4PLANNER_TEST_PYTHON").expect("test Python"));
    let root = std::env::temp_dir().join(format!("local-report-process-{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(root.join("private")).unwrap();
    assert_eq!(
        LocalGateway::start(&python, &root).err().unwrap(),
        "REPORT_NOT_CONFIGURED"
    );
    fs::write(
        root.join("private/report-config.json"),
        r#"{"githubToken":"SYNTHETIC_NEVER_SEND","recipient":"age1invalid","maxBytes":1000}"#,
    )
    .unwrap();
    assert_eq!(
        LocalGateway::start(&python, &root).err().unwrap(),
        "RECIPIENT_NOT_CONFIGURED"
    );
    assert!(!root.join("private/report-gateway.sqlite3").exists());
    fs::remove_dir_all(root).unwrap();
}

#[test]
#[ignore = "requires explicit test-only sitecustomize fixture and fake-state path"]
fn real_native_http_encrypt_upload_and_restart_retry() {
    use d4planner_report_issue::{Description, Report, Selection};
    use std::io::Read;
    let state =
        PathBuf::from(std::env::var("D4PLANNER_REPORT_FAKE_STATE").expect("explicit fake state"));
    let python = PathBuf::from(std::env::var("D4PLANNER_TEST_PYTHON").expect("test Python"));
    let root = std::env::temp_dir().join(format!("local-report-e2e-{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(root.join("private")).unwrap();
    let identity = age::x25519::Identity::generate();
    fs::write(root.join("private/report-config.json"),serde_json::json!({
        "githubToken":"SYNTHETIC_GITHUB_PAT_NEVER_EXPORT", "recipient":identity.to_public().to_string(),"maxBytes":10000000
    }).to_string()).unwrap();
    let session =
        d4planner_runtime_logging::Session::create(&root, "test", "local-gateway-fixture").unwrap();
    let mut report = Report::collect(
        &root,
        &session.id,
        Selection {
            fe: true,
            be: false,
            rulekit: false,
            evidence: false,
            evidence_consent: false,
        },
        |_| panic!("unselected source"),
    )
    .unwrap();
    let description = Description {
        issue_type: "Other".into(),
        title: "Synthetic native test".into(),
        actual: "a".into(),
        expected: "b".into(),
        steps: "fixture".into(),
    };
    let first = LocalGateway::start(&python, &root).unwrap();
    let outcome = report
        .attempt(
            first.config(),
            Ok(first.credential().into()),
            &description,
            true,
        )
        .unwrap();
    assert_eq!(outcome["status"], "COMPLETE");
    drop(first);
    let second = LocalGateway::start(&python, &root).unwrap();
    assert_eq!(
        report
            .attempt(
                second.config(),
                Ok(second.credential().into()),
                &description,
                true
            )
            .unwrap()["status"],
        "COMPLETE"
    );
    drop(second);
    let remote: serde_json::Value = serde_json::from_slice(&fs::read(&state).unwrap()).unwrap();
    assert_eq!(remote["items"].as_array().unwrap().len(), 1);
    assert_eq!(remote["uploads"].as_array().unwrap().len(), 1);
    let encrypted = fs::read(state.with_extension("age")).unwrap();
    let decrypt = age::Decryptor::new(&encrypted[..]).unwrap();
    let mut reader = decrypt
        .decrypt(std::iter::once(&identity as &dyn age::Identity))
        .unwrap();
    let mut zip = Vec::new();
    reader.read_to_end(&mut zip).unwrap();
    let mut archive = zip::ZipArchive::new(std::io::Cursor::new(zip)).unwrap();
    for i in 0..archive.len() {
        let mut file = archive.by_index(i).unwrap();
        assert!(!file.name().contains("config"));
        let mut content = String::new();
        file.read_to_string(&mut content).unwrap();
        assert!(!content.contains("SYNTHETIC_GITHUB_PAT_NEVER_EXPORT"));
    }
    report.discard().unwrap();
    drop(session);
    fs::remove_dir_all(root).unwrap();
}
