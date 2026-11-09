//! Native age decryption for RuleKit's UI provisioner; never exposed as a WebView command.
use std::{
    collections::HashSet,
    fs::{self, OpenOptions},
    io::{Cursor, Read},
    path::Path,
};
const ENCRYPTED: u64 = 128 * 1024 * 1024;
const ZIP: u64 = 256 * 1024 * 1024;
const TOTAL: u64 = 512 * 1024 * 1024;
const ENTRY: u64 = 32 * 1024 * 1024;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn safe_ancestors(path: &Path) -> Result<()> {
    for ancestor in path.ancestors() {
        if let Ok(meta) = fs::symlink_metadata(ancestor) {
            if meta.file_type().is_symlink() {
                return Err("link".into());
            }
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                if meta.file_attributes() & 0x400 != 0 {
                    return Err("reparse point".into());
                }
            }
        }
    }
    Ok(())
}
fn member(name: &str) -> Result<()> {
    if name.len() > 220 || name.contains('\\') || name.contains(':') {
        return Err("path".into());
    }
    for part in name.split('/') {
        let stem = part.split('.').next().unwrap_or("").to_ascii_uppercase();
        if part.is_empty()
            || part == "."
            || part == ".."
            || part.ends_with(['.', ' '])
            || part
                .chars()
                .any(|c| c.is_control() || "<>\"|?*".contains(c))
            || [
                "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7",
                "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8",
                "LPT9",
            ]
            .contains(&stem.as_str())
        {
            return Err("path".into());
        }
    }
    Ok(())
}
fn extract(bytes: Vec<u8>, destination: &Path) -> Result<()> {
    let mut zip = zip::ZipArchive::new(Cursor::new(bytes))?;
    if zip.len() > 20_000 {
        return Err("count".into());
    }
    let mut names = HashSet::new();
    let mut total = 0u64;
    for i in 0..zip.len() {
        let entry = zip.by_index(i)?;
        member(entry.name())?;
        if entry.is_dir()
            || entry
                .unix_mode()
                .is_some_and(|m| m & 0o170000 != 0 && m & 0o170000 != 0o100000)
            || !names.insert(entry.name().to_lowercase())
            || entry.size() > ENTRY
        {
            return Err("entry".into());
        }
        total = total.checked_add(entry.size()).ok_or("size")?;
        if total > TOTAL {
            return Err("size".into());
        }
    }
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i)?;
        let file = destination.join(entry.name());
        fs::create_dir_all(file.parent().ok_or("parent")?)?;
        safe_ancestors(&file)?;
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut output = options.open(file)?;
        let size = entry.size();
        let copied = std::io::copy(&mut (&mut entry).take(ENTRY + 1), &mut output)?;
        if copied != size {
            return Err("size".into());
        }
    }
    Ok(())
}
fn run(archive: &Path, identity: &Path, destination: &Path) -> Result<()> {
    if !archive.is_absolute() || !identity.is_absolute() || !destination.is_absolute() {
        return Err("absolute".into());
    }
    for p in [archive, identity, destination] {
        safe_ancestors(p)?;
    }
    if fs::metadata(archive)?.len() > ENCRYPTED || fs::metadata(identity)?.len() > 8192 {
        return Err("size".into());
    }
    let keys = fs::read_to_string(identity)?;
    let identities: Vec<age::x25519::Identity> = keys
        .lines()
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.starts_with('#'))
        .map(|s| s.parse().map_err(|_| "identity".into()))
        .collect::<Result<_>>()?;
    if identities.len() != 1 {
        return Err("identity".into());
    }
    let input = fs::read(archive)?;
    let decryptor = age::Decryptor::new(input.as_slice())?;
    let reader = decryptor.decrypt(identities.iter().map(|i| i as &dyn age::Identity))?;
    let mut plain = Vec::new();
    reader.take(ZIP + 1).read_to_end(&mut plain)?;
    if plain.len() as u64 > ZIP {
        return Err("size".into());
    }
    // Never delete a destination which this invocation did not create.
    fs::create_dir(destination)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(destination, fs::Permissions::from_mode(0o700))?;
    }
    let result = extract(plain, destination);
    if result.is_err() {
        let _ = fs::remove_dir_all(destination);
    }
    result
}
pub fn unpack(
    archive: &Path,
    identity: &Path,
    destination: &Path,
) -> std::result::Result<(), &'static str> {
    run(archive, identity, destination).map_err(|_| "PLANNER_DECRYPTION_FAILED")
}

#[cfg(test)]
mod tests {
    use super::*;
    use age::secrecy::ExposeSecret;
    use std::io::Write;
    fn fixture(names: &[&str]) -> (std::path::PathBuf, std::path::PathBuf, std::path::PathBuf) {
        let root = std::env::temp_dir().join(format!("planner-unpack-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let key = age::x25519::Identity::generate();
        let identity = root.join("identity");
        fs::write(&identity, key.to_string().expose_secret()).unwrap();
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        for name in names {
            zip.start_file(*name, zip::write::SimpleFileOptions::default())
                .unwrap();
            zip.write_all(b"fixture").unwrap();
        }
        let bytes = zip.finish().unwrap().into_inner();
        let archive = root.join("snapshot.age");
        let recipient = key.to_public();
        let encryptor =
            age::Encryptor::with_recipients(std::iter::once(&recipient as &dyn age::Recipient))
                .unwrap();
        let mut writer = encryptor
            .wrap_output(fs::File::create(&archive).unwrap())
            .unwrap();
        writer.write_all(&bytes).unwrap();
        writer.finish().unwrap();
        (root, archive, identity)
    }
    #[test]
    fn age_roundtrip_and_no_overwrite() {
        let (root, archive, key) = fixture(&["snapshot/manifest.json"]);
        let dest = root.join("out");
        assert!(unpack(&archive, &key, &dest).is_ok());
        assert_eq!(
            fs::read(dest.join("snapshot/manifest.json")).unwrap(),
            b"fixture"
        );
        assert!(unpack(&archive, &key, &dest).is_err());
        assert!(dest.exists());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn wrong_key_and_unsafe_members_never_publish() {
        for names in [
            vec!["../escape"],
            vec!["C:/escape"],
            vec!["snapshot/CON.txt"],
            vec!["snapshot/a", "snapshot/A"],
            vec!["snapshot/a."],
        ] {
            let (root, archive, key) = fixture(&names);
            let dest = root.join("out");
            assert!(unpack(&archive, &key, &dest).is_err());
            assert!(!dest.exists());
            fs::remove_dir_all(root).unwrap();
        }
        let (root, archive, key) = fixture(&["snapshot/manifest.json"]);
        fs::write(
            &key,
            age::x25519::Identity::generate()
                .to_string()
                .expose_secret(),
        )
        .unwrap();
        assert!(unpack(&archive, &key, &root.join("out")).is_err());
        assert!(!root.join("out").exists());
        fs::remove_dir_all(root).unwrap();
    }
}
