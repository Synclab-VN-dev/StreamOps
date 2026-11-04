//! Native implementation of docs/unified-data-root.md (also tested on Linux).
use std::{collections::BTreeMap, fs, path::{Component, Path, PathBuf}};

pub fn canonical(path: &Path) -> Result<PathBuf, String> {
    if !path.is_absolute() || path.components().any(|c| matches!(c, Component::ParentDir)) {
        return Err("PATH_INCOMPATIBLE: absolute non-traversing DataRoot required".into());
    }
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(meta) => {
                #[cfg(windows)]
                { use std::os::windows::fs::MetadataExt;
                  if meta.file_attributes() & 0x400 != 0 { return Err("PATH_INCOMPATIBLE: reparse point".into()); } }
                if meta.file_type().is_symlink() { return Err("PATH_INCOMPATIBLE: symlink".into()); }
            },
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
            Err(error) => return Err(error.to_string()),
        }
    }
    let mut ancestor = path;
    let mut missing = Vec::new();
    while !ancestor.exists() {
        missing.push(ancestor.file_name().ok_or("Invalid root")?.to_owned());
        ancestor = ancestor.parent().ok_or("Invalid root")?;
    }
    let mut result = dunce::canonicalize(ancestor).map_err(|e| e.to_string())?;
    for part in missing.iter().rev() { result.push(part); }
    Ok(result)
}

pub fn check_owner(path: &Path) -> Result<(),String> {
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        let system=std::env::var_os("SYSTEMROOT").ok_or("Windows system directory unavailable")?;
        let result=std::process::Command::new(PathBuf::from(system).join("System32/WindowsPowerShell/v1.0/powershell.exe"))
            .args(["-NoProfile","-NonInteractive","-Command",include_str!("../../d4planner-be/src/d4planner/runtime/storage_acl.ps1")])
            .env("D4PLANNER_ACL_PATH",path).creation_flags(0x08000000)
            .output().map_err(|e|e.to_string())?;
        if !result.status.success() { return Err("PATH_INCOMPATIBLE: owner/ACL verification failed".into()); }
    }
    #[cfg(not(windows))] { let _=path; }
    Ok(())
}

fn inventory_names(root: &Path, directory: &Path, names: &mut std::collections::BTreeSet<String>) -> Result<(),String> {
    for entry in fs::read_dir(directory).map_err(|e|e.to_string())? {
        let path=entry.map_err(|e|e.to_string())?.path();
        if path.file_name().is_some_and(|name| name == ".storage-migrated.json" || name == ".storage-migration-active.json") { continue; }
        canonical(&path)?;
        if path.is_dir() { inventory_names(root,&path,names)?; }
        else { names.insert(path.strip_prefix(root).map_err(|e|e.to_string())?.to_string_lossy().replace('\\',"/")); }
    }
    Ok(())
}

pub fn resolve(installation: &Path, registered: Option<&Path>, env: &BTreeMap<String,String>) -> Result<PathBuf,String> {
    let mut roots = Vec::new();
    let isolated = env.get("D4PLANNER_STORAGE_ISOLATED").map(String::as_str) == Some("1");
    if isolated && !env.contains_key("D4PLANNER_DATA_ROOT") { return Err("Explicit isolated DataRoot required".into()); }
    if !isolated {
        if let Some(path) = registered { roots.push(canonical(path)?); }
    }
    for key in ["D4PLANNER_DATA_ROOT", "D4PLANNER_HOME"] {
        if let Some(value) = env.get(key) { roots.push(canonical(Path::new(value))?); }
    }
    let local = env.get("LOCALAPPDATA").map(PathBuf::from);
    let root = if let Some(root) = roots.first() { root.clone() }
        else { canonical(&local.as_ref().ok_or("LOCALAPPDATA is required")?.join("StreamOps/D4Planner"))? };
    if root.join(".storage-migrated.json").exists() { return Err("MIGRATION_REQUIRED: select canonical target".into()); }
    if root.exists() { check_owner(&root)?; }
    if isolated {
        if let Some(path) = registered {
            let registered = canonical(path)?;
            if root.starts_with(&registered) || registered.starts_with(&root) { return Err("Isolated DataRoot must be disjoint from registered root".into()); }
        }
    }
    if roots.iter().any(|r| r != &root) { return Err("PATH_CONFLICT: registered/override roots disagree".into()); }
    if root.starts_with(canonical(installation)?) { return Err("DataRoot must be outside installation".into()); }
    for (key, child) in [("D4PLANNER_DATA_DIR","state"), ("D4_RULEKIT_DATA_ROOT","rulekit")] {
        if let Some(value) = env.get(key) {
            if canonical(Path::new(value))? != root.join(child) { return Err(format!("PATH_CONFLICT: {key}")); }
        }
    }
    if roots.is_empty() || local.as_ref().map(|p| p.join("StreamOps/D4Planner")) == Some(root.clone()) {
        if let Some(local) = local {
            let legacy = local.join("d4planner"); // LEGACY: migration detection only.
            if legacy.exists() && fs::read_dir(legacy).map_err(|e|e.to_string())?.next().is_some() {
                let receipt: serde_json::Value = fs::read(root.join("private/storage-origin.json")).ok()
                    .and_then(|bytes|serde_json::from_slice(&bytes).ok()).ok_or("MIGRATION_REQUIRED: use d4planner storage migrate")?;
                if receipt["status"] != "VERIFIED" || receipt["source"].as_str().map(PathBuf::from) != Some(local.join("d4planner")) {
                    return Err("MIGRATION_REQUIRED: invalid migration receipt".into());
                }
                let mut actual=std::collections::BTreeSet::new();
                inventory_names(&local.join("d4planner"),&local.join("d4planner"),&mut actual)?;
                let entries=receipt["files"].as_array().ok_or("Invalid migration receipt")?;
                let recorded: std::collections::BTreeSet<String> = entries.iter().map(|entry| entry["sourcePath"].as_str().unwrap_or("").to_owned()).collect();
                if actual != recorded { return Err("MIGRATION_REQUIRED: legacy inventory changed".into()); }
                for entry in entries {
                    let relative=Path::new(entry["sourcePath"].as_str().ok_or("Invalid receipt path")?);
                    if relative.is_absolute() || relative.components().any(|c| !matches!(c,Component::Normal(_))) {
                        return Err("Invalid migration receipt path".into());
                    }
                    if super::digest(&local.join("d4planner").join(relative))? != entry["sourceSha256"].as_str().ok_or("Invalid receipt hash")? {
                        return Err("MIGRATION_REQUIRED: changed legacy source".into());
                    }
                }
            }
        }
    }
    if root.join("private/storage-migration.json").exists() || root.join(".storage-migration-active.json").exists() { return Err("MIGRATION_REQUIRED: unfinished migration".into()); }
    Ok(root)
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn shared_python_native_contract() {
        let cases: serde_json::Value = serde_json::from_str(include_str!("../../d4planner-be/tests/fixtures/unified-storage-cases.json")).unwrap();
        let root=std::env::temp_dir().join(format!("udr-matrix-{}",uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let expand=|value: &str| value.replace("@root", &root.to_string_lossy());
        for case in cases.as_array().unwrap() {
            let env=case["env"].as_object().unwrap().iter().map(|(k,v)|(k.clone(),expand(v.as_str().unwrap()))).collect();
            let registered=case["registered"].as_str().map(|v|PathBuf::from(expand(v)));
            let actual=resolve(&root.join("install"),registered.as_deref(),&env);
            if let Some(error)=case["error"].as_str() {
                assert!(actual.unwrap_err().contains(error), "{}", case["name"]);
            } else {
                assert_eq!(actual.unwrap(), PathBuf::from(expand(case["expected"].as_str().unwrap())), "{}",case["name"]);
            }
        }
        fs::remove_dir_all(root).unwrap();
    }
    #[test] fn defaults_and_conflicts() {
        let dir=std::env::temp_dir().join(format!("udr-{}",uuid::Uuid::new_v4()));
        fs::create_dir_all(&dir).unwrap();
        let mut env=BTreeMap::from([("LOCALAPPDATA".into(),dir.to_string_lossy().into_owned())]);
        let install=dir.join("Programs/App");
        assert_eq!(resolve(&install,None,&env).unwrap(),dir.join("StreamOps/D4Planner"));
        env.insert("D4PLANNER_HOME".into(),dir.join("custom").to_string_lossy().into_owned());
        assert!(resolve(&install,Some(&dir.join("registered")),&env).unwrap_err().contains("PATH_CONFLICT"));
        fs::remove_dir_all(dir).unwrap();
    }
}
