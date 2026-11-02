"""Component-owned CI commands migrated from the corresponding native workflows."""
CI_SPEC = {'version': 1,
 'id': 'd4planner-hud',
 # Legacy source paths remain watched while migration is compared with master.
 'watch': ['scripts/local/d4-overlay-poc.ps1',
           'utility/d4planner-overlay-poc/**',
           '.github/workflows/main.yml', '.github/workflows/ci.py', 'scripts/e2e/d4-overlay-poc-smoke.ps1'],
 'depends_on': [],
 'jobs': [{'id': 'native', 'profile': 'windows', 'timeout': 3600, 'tools': {'node': '22', 'rust': 'stable'}}]}

def run(ctx):
    if ctx.job['id'] == 'native':
        # d4-overlay-poc.yml / windows-exe: Install frontend dependencies
        ctx.shell(r'''
npm install --no-audit --no-fund
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: Generate Windows icon
        ctx.shell(r'''
npm run icon
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: React unit + IPC interaction tests
        ctx.shell(r'''
npm test
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: Compile React bundle
        ctx.shell(r'''
npm run build
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: Rust runtime logging tests
        ctx.shell(r'''
cargo test --locked --manifest-path runtime-logging/Cargo.toml
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: Rust report archive/encryption/retry tests
        ctx.shell(r'''
cargo test --locked --manifest-path report-issue/Cargo.toml
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: Rust mode/hotkey tests
        ctx.shell(r'''
cargo test --manifest-path src-tauri/Cargo.toml
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: Build portable Windows EXE
        ctx.shell(r'''
npm run tauri:build
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: Static + real native GUI smoke (fail if unavailable)
        ctx.shell(r'''
$exe = "src-tauri/target/release/d4planner-overlay-poc.exe"
& (Join-Path $env:GITHUB_WORKSPACE "scripts/e2e/d4-overlay-poc-smoke.ps1") -ExePath $exe -Runtime -TimeoutSeconds 60
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        # d4-overlay-poc.yml / windows-exe: Package artifact
        ctx.shell(r'''
$exe = "src-tauri/target/release/d4planner-overlay-poc.exe"
New-Item -ItemType Directory -Force portable | Out-Null
Copy-Item $exe portable/
Copy-Item README.md portable/README.md
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
"$hash  d4planner-overlay-poc.exe" | Set-Content portable/SHA256.txt -Encoding ascii
Write-Host "Portable EXE: $hash"
''', shell='pwsh', cwd='utility/d4planner/d4planner-hud')
        ctx.artifact('utility/d4planner/d4planner-hud/portable')
        return
    raise ValueError("UNKNOWN_JOB")
