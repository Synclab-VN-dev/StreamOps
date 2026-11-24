//! Bounded read-only export of the capture session identified by owned BE IPC.
//! Never select the newest DB session or copy a live database/WAL.
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::{
    fs,
    io::Write,
    path::Path,
    time::{Duration, Instant},
};

const MAX_BYTES: usize = 4_000_000;
const MAX_ROWS: usize = 100_000;

pub fn export(
    data: &Path,
    destination: &Path,
    session: impl FnMut() -> Result<String, String>,
) -> Result<Value, String> {
    export_recent(data, destination, session, MAX_ROWS, MAX_BYTES)
}

fn export_recent(
    data: &Path,
    destination: &Path,
    mut session: impl FnMut() -> Result<String, String>,
    max_rows: usize,
    max_bytes: usize,
) -> Result<Value, String> {
    let id = session()?;
    if id.len() != 32 || !id.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("EVENT_SESSION_INVALID".into());
    }
    let path = data.join("state/events.db");
    if !path.is_file() {
        return Err("EVENT_STORE_UNAVAILABLE".into());
    }
    for p in [
        &path,
        &path.with_extension("db-wal"),
        &path.with_extension("db-shm"),
        destination,
    ] {
        if !d4planner_runtime_logging::safe(p) {
            return Err("EVENT_PATH_UNSAFE".into());
        }
    }
    let db = Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|_| "EVENT_STORE_UNAVAILABLE")?;
    db.busy_timeout(Duration::from_secs(1))
        .map_err(|_| "EVENT_STORE_UNAVAILABLE")?;
    db.execute_batch("PRAGMA query_only=ON; BEGIN;")
        .map_err(|_| "EVENT_STORE_BUSY")?;
    let mut query = db.prepare("SELECT event_seq,timestamp,type,data_json,length(CAST(data_json AS BLOB)) FROM event_log WHERE session_id=? ORDER BY event_seq DESC LIMIT ?")
        .map_err(|_| "EVENT_SCHEMA_UNSUPPORTED")?;
    let mut rows = query
        .query(rusqlite::params![id, (max_rows + 1) as i64])
        .map_err(|_| "EVENT_STORE_BUSY")?;
    let start = Instant::now();
    let mut lines = Vec::new();
    let mut bytes = 0;
    let mut first = 0;
    let mut last = 0;
    let mut first_time = String::new();
    let mut last_time = String::new();
    let mut truncated = false;
    while let Some(row) = rows.next().map_err(|_| "EVENT_READ_FAILED")? {
        if start.elapsed() > Duration::from_secs(5) {
            return Err("EVENT_EXPORT_TIMEOUT".into());
        }
        if lines.len() == max_rows {
            truncated = true;
            break;
        }
        let seq: i64 = row.get(0).map_err(|_| "EVENT_SCHEMA_UNSUPPORTED")?;
        if seq <= 0 || (first != 0 && seq >= first) {
            return Err("EVENT_SEQUENCE_INVALID".into());
        }
        let length: i64 = row.get(4).map_err(|_| "EVENT_SCHEMA_UNSUPPORTED")?;
        if length < 0 {
            return Err("EVENT_SCHEMA_UNSUPPORTED".into());
        }
        if length as usize >= max_bytes - bytes {
            truncated = true;
            break;
        }
        let timestamp: String = row.get(1).map_err(|_| "EVENT_SCHEMA_UNSUPPORTED")?;
        let kind: String = row.get(2).map_err(|_| "EVENT_SCHEMA_UNSUPPORTED")?;
        let raw: String = row.get(3).map_err(|_| "EVENT_SCHEMA_UNSUPPORTED")?;
        let payload: Value = serde_json::from_str(&raw).map_err(|_| "EVENT_DATA_INVALID")?;
        if !payload.is_object() {
            return Err("EVENT_DATA_INVALID".into());
        }
        let line = serde_json::to_vec(&json!({
            "sessionId": id, "eventSeq": seq, "timestamp": timestamp, "type": kind, "data": payload,
        }))
        .map_err(|_| "EVENT_DATA_INVALID")?;
        if line.len() >= max_bytes - bytes {
            truncated = true;
            break;
        }
        if lines.is_empty() {
            last = seq;
            last_time = timestamp.clone();
        }
        first = seq;
        first_time = timestamp;
        bytes += line.len() + 1;
        lines.push(line);
    }
    if lines.is_empty() {
        return Err(if truncated {
            "EVENT_EXPORT_TOO_LARGE"
        } else {
            "EVENT_SESSION_EMPTY"
        }
        .into());
    }
    // Capture restart during collection must not silently relabel old evidence.
    if session()? != id {
        return Err("EVENT_SESSION_CHANGED".into());
    }
    fs::create_dir(destination).map_err(|_| "EVENT_EXPORT_FAILED")?;
    let out = destination.join("events.jsonl");
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&out)
        .map_err(|_| "EVENT_EXPORT_FAILED")?;
    let write = (|| -> std::io::Result<()> {
        for line in lines.iter().rev() {
            file.write_all(line)?;
            file.write_all(b"\n")?;
        }
        file.sync_all()
    })();
    if write.is_err() {
        drop(file);
        let _ = fs::remove_file(out);
        return Err("EVENT_EXPORT_FAILED".into());
    }
    Ok(
        json!({"files":[{"name":"events.jsonl","status":"BEST_EFFORT","sessionId":id,
        "eventCount":lines.len(),"olderEventsOmitted":truncated,"firstEventSeq":first,"lastEventSeq":last,"firstEventAt":first_time,"lastEventAt":last_time}]}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    const SESSION: &str = "0123456789abcdef0123456789abcdef";
    fn fixture() -> std::path::PathBuf {
        let p = std::env::temp_dir().join(format!("event-export-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(p.join("state")).unwrap();
        let db = Connection::open(p.join("state/events.db")).unwrap();
        db.execute_batch("PRAGMA journal_mode=WAL;CREATE TABLE event_log(session_id TEXT,event_seq INTEGER,timestamp TEXT,type TEXT,data_json TEXT); CREATE UNIQUE INDEX event_cursor ON event_log(session_id,event_seq);").unwrap();
        for id in [SESSION, "ffffffffffffffffffffffffffffffff"] {
            db.execute("INSERT INTO event_log VALUES(?,1,'2026-11-21T03:00:00Z','speech.raw','{\"text\":\"synthetic\"}')",[id]).unwrap();
        }
        p
    }
    #[test]
    fn exports_only_bound_session_with_receipt_and_no_db_mutation() {
        let p = fixture();
        let db = Connection::open(p.join("state/events.db")).unwrap();
        db.execute("INSERT INTO event_log VALUES(?,2,'2026-11-21T03:01:00Z','speech.raw','{\"text\":\"Ranged\"}')",[SESSION]).unwrap();
        let out = p.join("export");
        let result = export(&p, &out, || Ok(SESSION.into())).unwrap();
        assert_eq!(result["files"][0]["eventCount"], 2);
        assert_eq!(result["files"][0]["lastEventSeq"], 2);
        let lines = fs::read_to_string(out.join("events.jsonl")).unwrap();
        assert_eq!(lines.lines().count(), 2);
        assert!(!lines.contains("ffffffff"));
        assert_eq!(
            db.query_row("SELECT count(*) FROM event_log", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            3
        );
        drop(db);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn changed_unbound_empty_and_invalid_sessions_fail_without_partial_export() {
        let p = fixture();
        let mut calls = 0;
        assert_eq!(
            export(&p, &p.join("out"), || {
                calls += 1;
                Ok(if calls == 1 {
                    SESSION
                } else {
                    "ffffffffffffffffffffffffffffffff"
                }
                .into())
            })
            .unwrap_err(),
            "EVENT_SESSION_CHANGED"
        );
        assert!(!p.join("out").exists());
        assert_eq!(
            export(&p, &p.join("out"), || Err(
                "EVENT_SESSION_UNAVAILABLE".into()
            ))
            .unwrap_err(),
            "EVENT_SESSION_UNAVAILABLE"
        );
        assert_eq!(
            export(&p, &p.join("out"), || Ok("../foreign".into())).unwrap_err(),
            "EVENT_SESSION_INVALID"
        );
        assert_eq!(
            export(&p, &p.join("out"), || Ok(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into()
            ))
            .unwrap_err(),
            "EVENT_SESSION_EMPTY"
        );
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn retains_latest_events_in_order_when_row_or_byte_limit_is_hit() {
        let p = fixture();
        let db = Connection::open(p.join("state/events.db")).unwrap();
        for seq in 2..=5 {
            db.execute(
                "INSERT INTO event_log VALUES(?, ?, '2026-11-21T03:01:00Z', 'speech.raw', ?) ",
                rusqlite::params![SESSION, seq, r#"{"text":"latest"}"#],
            )
            .unwrap();
        }
        let full = export(&p, &p.join("full"), || Ok(SESSION.into())).unwrap();
        assert_eq!(full["files"][0]["olderEventsOmitted"], false);
        let scaled_byte_limit = fs::read_to_string(p.join("full/events.jsonl"))
            .unwrap()
            .lines()
            .rev()
            .take(2)
            .map(|line| line.len() + 1)
            .sum();
        for (label, rows, bytes) in [("row", 2, MAX_BYTES), ("byte", MAX_ROWS, scaled_byte_limit)] {
            let out = p.join(label);
            let receipt = export_recent(&p, &out, || Ok(SESSION.into()), rows, bytes).unwrap();
            assert_eq!(receipt["files"][0]["olderEventsOmitted"], true);
            assert_eq!(receipt["files"][0]["firstEventSeq"], 4);
            assert_eq!(receipt["files"][0]["lastEventSeq"], 5);
            let events: Vec<Value> = fs::read_to_string(out.join("events.jsonl"))
                .unwrap()
                .lines()
                .map(|line| serde_json::from_str(line).unwrap())
                .collect();
            assert_eq!(events.len(), 2);
            assert_eq!(events[0]["eventSeq"], 4);
            assert_eq!(events[1]["eventSeq"], 5);
            assert!(events.iter().all(|event| event["sessionId"] == SESSION));
        }
        drop(db);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn malformed_payload_and_oversize_fail_closed() {
        let p = fixture();
        let db = Connection::open(p.join("state/events.db")).unwrap();
        db.execute("UPDATE event_log SET data_json='broken'", [])
            .unwrap();
        assert_eq!(
            export(&p, &p.join("out"), || Ok(SESSION.into())).unwrap_err(),
            "EVENT_DATA_INVALID"
        );
        db.execute(
            "UPDATE event_log SET data_json=?",
            ["x".repeat(MAX_BYTES + 1)],
        )
        .unwrap();
        assert_eq!(
            export(&p, &p.join("out"), || Ok(SESSION.into())).unwrap_err(),
            "EVENT_EXPORT_TOO_LARGE"
        );
        drop(db);
        fs::remove_dir_all(p).unwrap();
    }
}
