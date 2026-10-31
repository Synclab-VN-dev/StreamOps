//! Public D5 SQLite projection. No renderer SQL, migrations or write connections.
use std::{path::Path, sync::OnceLock, time::Duration};
use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde_json::{json, Value};

fn sql_error(error: rusqlite::Error) -> String {
    match error.sqlite_error_code() {
        Some(rusqlite::ErrorCode::DatabaseBusy | rusqlite::ErrorCode::DatabaseLocked) => "DB_BUSY",
        Some(rusqlite::ErrorCode::DatabaseCorrupt | rusqlite::ErrorCode::NotADatabase) => "DB_CORRUPT",
        Some(rusqlite::ErrorCode::CannotOpen | rusqlite::ErrorCode::PermissionDenied) => "DB_UNREADABLE",
        _ => "DB_INCOMPATIBLE",
    }.into()
}

pub fn read_latest(data_dir: &Path) -> Result<Option<Value>, String> {
    if !data_dir.is_absolute() { return Err("CONFIGURATION_MISSING".into()); }
    let path = data_dir.join("hud.sqlite3");
    match std::fs::metadata(&path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("DB_UNREADABLE".into()),
        Ok(meta) if !meta.is_file() => return Err("DB_UNREADABLE".into()),
        _ => {}
    }
    let mut db = Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX).map_err(sql_error)?;
    db.busy_timeout(Duration::from_millis(200)).map_err(sql_error)?;
    db.pragma_update(None, "query_only", true).map_err(sql_error)?;
    let tx = db.transaction().map_err(sql_error)?;
    let (version, id, epoch): (String, String, String) = tx.query_row(
        "SELECT schema_version,db_id,epoch FROM hud_public_meta WHERE singleton=1", [],
        |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?))).map_err(sql_error)?;
    if version != "d4planner-hud-db/v1" || id.is_empty() || epoch.is_empty() || id.len() > 160 || epoch.len() > 160 {
        return Err("DB_INCOMPATIBLE".into());
    }
    let row: Option<(i64, String)> = tx.query_row("SELECT hud_revision,payload_json FROM hud_current WHERE singleton=1", [],
        |row| Ok((row.get(0)?,row.get(1)?))).optional().map_err(sql_error)?;
    let Some((revision, encoded)) = row else { return Ok(None); };
    if !(0..=9_007_199_254_740_991).contains(&revision) || encoded.len() > 4 * 1024 * 1024 { return Err("DB_INVALID_MODEL".into()); }
    let hud: Value = serde_json::from_str(&encoded).map_err(|_| "DB_INVALID_MODEL")?;
    static VALIDATOR: OnceLock<jsonschema::Validator> = OnceLock::new();
    let validator = VALIDATOR.get_or_init(|| {
        let schema: Value = serde_json::from_str(include_str!("../../../d4planner/contracts/release1/v1/schemas/hud.schema.json")).expect("embedded HUD schema");
        jsonschema::validator_for(&schema).expect("valid embedded HUD schema")
    });
    if !validator.is_valid(&hud) || hud["hudRevision"].as_i64() != Some(revision) { return Err("DB_INVALID_MODEL".into()); }
    if hud["context"]["state"] == "BOUND" {
        let ctx = &hud["context"];
        let binding = &ctx["binding"];
        for (left, right) in [
            (&binding["runtimeInstanceId"], &hud["backend"]["runtimeInstanceId"]),
            (&binding["characterId"], &ctx["character"]["characterId"]),
            (&binding["currentRevision"], &ctx["character"]["currentRevision"]),
            (&binding["targetId"], &ctx["target"]["targetId"]),
            (&binding["targetSha256"], &ctx["target"]["contentSha256"]),
            (&binding["selectionRevision"], &ctx["target"]["selectionRevision"]),
            (&binding["policyVersion"], &ctx["target"]["policyVersion"]),
        ] { if left != right { return Err("DB_BINDING_MISMATCH".into()); } }
    }
    Ok(Some(json!({"schemaVersion":version,"dbId":id,"epoch":epoch,"hudRevision":revision,"hud":hud})))
}
