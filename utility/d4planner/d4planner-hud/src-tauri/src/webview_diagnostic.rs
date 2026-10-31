//! Bounded UAT state projection; never persist frontend payloads or exceptions.
use serde_json::{json, Value};

pub fn detail(phase: &str, raw: Option<&str>) -> Result<Option<String>, String> {
    if phase != "HUD_STATE" {
        return if matches!(phase, "BOOTSTRAP_STARTED" | "APP_MOUNT_REQUESTED" |
            "WINDOW_ERROR" | "UNHANDLED_REJECTION" | "APP_IMPORT_FAILED") {
            Ok(None)
        } else { Err("invalid diagnostic phase".into()) };
    }
    let raw = raw.ok_or("missing HUD state")?;
    if raw.len() > 2048 { return Err("diagnostic detail too large".into()); }
    let value: Value = serde_json::from_str(raw).map_err(|_| "invalid HUD state")?;
    if !value.is_object() { return Err("invalid HUD state".into()); }
    fn enumeration(value: &Value, allowed: &[&str]) -> Value {
        match value.as_str() {
            Some(text) if allowed.contains(&text) => Value::String(text.into()),
            Some(_) => Value::String("UNKNOWN".into()),
            None => Value::Null,
        }
    }
    let projection = json!({
        "connection": enumeration(&value["connection"], &["CONNECTING", "CONNECTED", "DISCONNECTED"]),
        "error": enumeration(&value["error"], &["OFFLINE", "DB_BUSY", "DB_MISSING", "DB_CORRUPT", "DB_UNREADABLE", "DB_INCOMPATIBLE", "DB_INVALID_MODEL", "DB_BINDING_MISMATCH"]),
        "hudRevision": value["hudRevision"].as_u64().filter(|n| *n <= 9_007_199_254_740_991),
        "contextState": enumeration(&value["contextState"], &["BOUND", "UNBOUND"]),
        "scoreStatus": enumeration(&value["scoreStatus"], &["SCORED", "NO_DATA"]),
    });
    Ok(Some(projection.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn offline_viewer_projection_survives_privacy_filter() {
        let state = json!({"connection":"DISCONNECTED","error":"OFFLINE","hudRevision":3,"contextState":"BOUND","scoreStatus":"SCORED"});
        let actual: Value = serde_json::from_str(&detail("HUD_STATE", Some(&state.to_string())).unwrap().unwrap()).unwrap();
        assert_eq!(actual, state);
    }
    #[test]
    fn unknown_fields_and_exception_text_never_reach_disk() {
        let state = json!({"connection":"SECRET_CANARY", "error":"SECRET_CANARY", "token":"SECRET_CANARY", "equipment":{"raw":"SECRET_CANARY"}});
        assert!(!detail("HUD_STATE", Some(&state.to_string())).unwrap().unwrap().contains("SECRET_CANARY"));
        assert_eq!(detail("WINDOW_ERROR", Some("SECRET_CANARY")).unwrap(), None);
    }
    #[test]
    fn arbitrary_phases_and_unbounded_state_fail_closed() {
        assert!(detail("SECRET_CANARY", None).is_err());
        assert!(detail("HUD_STATE", Some(&"x".repeat(2049))).is_err());
        assert!(detail("HUD_STATE", Some("[]")).is_err());
    }
}
