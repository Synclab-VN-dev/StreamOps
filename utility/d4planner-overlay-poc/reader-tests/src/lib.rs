#[path = "../../src-tauri/src/hud_reader.rs"]
pub mod hud_reader;

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;
    use serde_json::Value;
    struct Sandbox(std::path::PathBuf);
    impl Sandbox {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!("d5-reader-{}-{}",std::process::id(),std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
            std::fs::create_dir(&path).unwrap(); Self(path)
        }
        fn seed(&self) -> Connection {
            let db = Connection::open(self.0.join("hud.sqlite3")).unwrap();
            db.execute_batch(include_str!("../../../d4planner/contracts/release1/v1/hud-db.sql")).unwrap();
            db.pragma_update(None,"journal_mode","WAL").unwrap();
            db.execute("INSERT INTO hud_public_meta VALUES(1,'d4planner-hud-db/v1','db','epoch')",[]).unwrap();
            let hud: Value = serde_json::from_str(include_str!("../../../d4planner/contracts/release1/v1/fixtures/hud.partial.synthetic.json")).unwrap();
            db.execute("INSERT INTO hud_current VALUES(1,?,?)",rusqlite::params![hud["hudRevision"].as_i64().unwrap(),hud.to_string()]).unwrap(); db
        }
    }
    impl Drop for Sandbox { fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); } }
    #[test]
    fn offline_read_and_missing_do_not_create_database() {
        let root = Sandbox::new();
        assert!(hud_reader::read_latest(&root.0).unwrap().is_none());
        assert!(!root.0.join("hud.sqlite3").exists());
        let db = root.seed(); drop(db);
        let before = std::fs::read(root.0.join("hud.sqlite3")).unwrap();
        let model = hud_reader::read_latest(&root.0).unwrap().unwrap();
        assert_eq!(model["dbId"],"db");
        assert_eq!(before,std::fs::read(root.0.join("hud.sqlite3")).unwrap());
    }
    #[test]
    fn concurrent_writer_uncommitted_data_is_never_visible() {
        let root=Sandbox::new(); let db=root.seed();
        db.execute_batch("BEGIN IMMEDIATE; UPDATE hud_current SET payload_json='broken'").unwrap();
        assert!(hud_reader::read_latest(&root.0).unwrap().is_some());
        db.execute_batch("COMMIT").unwrap();
        assert_eq!(hud_reader::read_latest(&root.0).unwrap_err(),"DB_INVALID_MODEL");
    }
    #[test]
    fn corrupt_incompatible_binding_and_revision_fail_closed() {
        let root=Sandbox::new(); let db=root.seed();
        db.execute("UPDATE hud_current SET hud_revision=hud_revision+1",[]).unwrap();
        assert_eq!(hud_reader::read_latest(&root.0).unwrap_err(),"DB_INVALID_MODEL");
        drop(db); std::fs::write(root.0.join("hud.sqlite3"),b"not a database").unwrap();
        assert_eq!(hud_reader::read_latest(&root.0).unwrap_err(),"DB_CORRUPT");
    }
}
