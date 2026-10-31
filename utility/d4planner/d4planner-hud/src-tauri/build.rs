fn main() {
    // With Rust's full static CRT enabled, do not also ask Tauri to force
    // dynamic UCRT: those linker policies conflict (including bundled SQLite).
    let full_static_crt = std::env::var("CARGO_CFG_TARGET_FEATURE")
        .unwrap_or_default().split(',').any(|feature| feature == "crt-static");
    let attributes = if full_static_crt {
        tauri_build::Attributes::new().windows_attributes(
            tauri_build::WindowsAttributes::new().static_vc_runtime(false),
        )
    } else {
        tauri_build::Attributes::new()
    };
    tauri_build::try_build(attributes).expect("Tauri build failed");
}
