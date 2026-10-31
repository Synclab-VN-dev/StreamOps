# D4Planner source components

Architecture authority: [issue #138](https://github.com/Synclab-VN-dev/StreamOps/issues/138),
D5 DB-first / FE-independent. This source layout does not change the application,
process boundaries, public contracts or installed product layout.

```text
utility/d4planner/
├── d4planner-launcher/  # Native root bootstrap and owned process cleanup
├── d4planner-be/        # Python backend, contracts and release-specific tooling
├── d4planner-hud/       # Tauri native reader/process wrapper and React HUD
└── d4planner-rulekit/   # Rule Kit application, providers, browser and snapshots
```

| Previous source | Current source |
| --- | --- |
| `utility/d4planner/release1/native-launcher/` | `d4planner-launcher/` |
| `utility/d4planner/` (except native launcher) | `d4planner-be/` |
| `utility/d4planner-overlay-poc/` | `d4planner-hud/` |
| `utility/d4-rulekit/` | `d4planner-rulekit/` |

Launcher is an application bootstrap component, not another business domain.
`d4planner-be/release1/` retains installer, manifest, acceptance and UAT ownership
for this migration. TODO: its cross-component packaging responsibility is broader
than BE; a future ownership change needs a separate decision.

## Development and local verification

Commands below run from the repository root unless a working directory is shown.
Use isolated virtualenvs, build targets, caches and DataDirs.

```sh
python -m venv .venv
.venv/bin/python -m pip install -e 'utility/d4planner/d4planner-be[dev]'
.venv/bin/python -m pytest --collect-only utility/d4planner/d4planner-be/tests
.venv/bin/python -m pytest utility/d4planner/d4planner-be/tests/contracts
```

Windows uses `.venv/Scripts/python.exe`. Tests that require Windows APIs must run
on Windows; successful Linux collection is not Windows acceptance.

```sh
cd utility/d4planner/d4planner-hud
npm ci
npm test
npm run build
npm run icon
cargo test --locked --manifest-path reader-tests/Cargo.toml
cargo test --locked --manifest-path lifecycle-tests/Cargo.toml
# On a Windows build host with MSVC/WebView2:
npm run tauri:build
```

Run `npm ci` and the documented tests in the Rule Kit `application`,
`browser-infra`, `providers/maxroll`, and `snapshot-management` directories.
Browser tests require an explicitly provisioned Chromium. Private snapshot/real
provider gates must not be replaced by synthetic evidence.

```sh
cd utility/d4planner/d4planner-launcher
cargo test --locked
cargo build --locked --release
```

Build the launcher from its directory so Cargo loads `.cargo/config.toml` and the
static Windows CRT settings. Production assembly is still orchestrated by
`d4planner-be/tools/release_ci.py`; the existing approval policy is unchanged.

## Source paths versus installed paths

The assembler maps relocated source inputs into the existing package contract:

- Root `D4Planner.exe` launches `app/d4planner-fe.exe`.
- Tauri owns `python -m d4planner.managed_backend` and its control IPC.
- The adapter remains `backend/site-packages/d4planner/rulekit/worker.js`.
- Installed Rule Kit modules remain under `utility/d4-rulekit/`.
- Installed schemas remain under `utility/d4planner/contracts/`.
- Package names, executable names, CLI names, product IDs, DataDir,
  `hud.sqlite3`, Targets and Settings are unchanged.

BE commits SQLite; native Tauri reads the public model read-only. WebSocket carries
notification metadata only. Rule Kit retains runtime composition and its eight
Application APIs. FE does not calculate scores or call Rule Kit directly.

Historical review/evidence documents keep the paths that existed at capture time;
use the mapping above to navigate those records. Live commands/workflows use the
new locations. Folder migration does not authorize release, deployment, live-game
tests or changes to production runtime.
