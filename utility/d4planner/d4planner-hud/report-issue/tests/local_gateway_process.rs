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
