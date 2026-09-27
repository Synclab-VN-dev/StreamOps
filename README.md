# StreamOps

Automation and control-plane repository for the livestream system.

`StreamOps` is the source of truth for OBS automation, livestream orchestration, reusable scripts, configuration, verification evidence, and engineering backlog.

The primary operator is a Codex agent running on the Windows host. The agent should make reproducible changes through code/configuration, apply them through supported APIs such as OBS WebSocket, verify the result, and leave reviewable evidence for human approval.

---

## 1. Goals

The project aims to minimize manual setup on the livestream Windows host.

Typical tasks include:

- Create and configure OBS scenes.
- Add/remove/configure OBS sources.
- Position, scale, crop, and reorder scene items.
- Configure audio levels and filters.
- Apply transitions.
- Configure recording and streaming workflows.
- Inspect the current OBS state.
- Verify that the actual OBS state matches the desired state.
- Capture preview screenshots for review.
- Start/stop/recover livestream-related processes.
- Provide commands that can be triggered remotely from the Android orchestration device.
- Keep all changes reproducible and version-controlled.
- Maintain a backlog of future automation work.

The desired workflow is:

```text
Human request
     ↓
Codex agent
     ↓
Update code / desired-state config
     ↓
Dry-run / diff
     ↓
Apply via OBS WebSocket or supported API
     ↓
Verify actual state
     ↓
Capture evidence
     ↓
Human review / acceptance
```

Manual UI automation should be treated as a last resort.

---

## 2. System topology

The livestream system uses four logical devices.

### A — Windows Host

```text
IP: 192.168.1.8
OS: Windows
```

Responsibilities:

- Gaming host.
- Steam host.
- Steam Remote Play host.
- OBS host.
- Video encoding and recording.
- Runs the Codex agent.
- Runs StreamOps automation.
- Receives SSH control from B.
- Receives the camera stream from D.

### B — Android Orchestrator

```text
IP: 192.168.1.17
OS: Android + Termux
```

Responsibilities:

- Administration and orchestration.
- SSH control of A.
- Run remote StreamOps commands.
- Recovery when Steam Link, OBS, a game, or the controller path fails.
- Eventually act as the main remote control for livestream operations.

Example:

```text
B
│
│ SSH
▼
A
```

### C — Android Tablet

Responsibilities:

- Steam Link client.
- Main remote gaming UI.
- Xbox controller connects to C over Bluetooth.

Input path:

```text
Xbox Controller
      ↓ Bluetooth
C / Android Tablet
      ↓ Steam Link
A / Windows
      ↓
Game
```

### D — Android Camera

```text
IP: 192.168.1.7
OS: Android
```

Responsibilities:

- Wireless livestream camera.
- Sends video to A over LAN/Wi-Fi.
- Used as an OBS source.

Camera path:

```text
D / Android Camera
      ↓ LAN / Wi-Fi
A / Windows
      ↓
OBS
```

### Complete logical topology

```text
                         LAN
                  ┌─────────────────┐
                  │     Router      │
                  └───────┬─────────┘
                          │
             ┌────────────┼────────────┐
             │            │            │
             ▼            ▼            ▼

       A / Windows    B / Android    D / Android
       192.168.1.8    192.168.1.17   192.168.1.7
             ▲            │
             │            │ SSH
             └────────────┘

             ▲
             │ Steam Link
             │
        C / Android
          Tablet
             ▲
             │ Bluetooth
             │
      Xbox Controller
```

---

## 3. Repository role

This repository is the **engineering source of truth**.

Current location on A:

```text
C:\Users\huy\codex-work\StreamOps
```

Development and runtime both stay in this repository:

```text
C:\Users\huy\codex-work\StreamOps
├── .venv\             # repo-local Python environment
├── .streamops\node\   # ignored runtime state, captures, and logs
├── scripts\            # lifecycle commands
└── streamops\          # application source
```

Do not copy or deploy StreamOps source and commands into `C:\Scripts`. Existing files there are preserved.

---

## 4. Design principles

### 4.1 Desired state over imperative clicking

Prefer:

```text
desired configuration
        ↓
apply
        ↓
verify
```

instead of:

```text
click UI
click UI
click UI
```

For example, a scene should ideally be represented as data:

```json
{
  "scene": "Gaming",
  "sources": {
    "game": {
      "role": "game",
      "enabled": true
    },
    "camera": {
      "role": "camera",
      "enabled": true,
      "anchor": "bottom-right",
      "width_percent": 22
    }
  }
}
```

The automation layer translates that desired state into OBS WebSocket operations.

### 4.2 Idempotency

Running the same apply command twice should not duplicate scenes, sources, or filters.

Bad:

```text
run #1 → Camera-D
run #2 → Camera-D 2
run #3 → Camera-D 3
```

Expected:

```text
run #1 → create Camera-D
run #2 → no change
run #3 → no change
```

### 4.3 Inspect before mutate

Before changing OBS:

1. Read current state.
2. Calculate the difference.
3. Report the planned changes.
4. Apply only the required mutations.

### 4.4 Verify after apply

Do not assume a successful API response means the scene is correct.

Verification should check:

- Scene exists.
- Expected sources exist.
- Source settings match.
- Transform matches.
- Visibility matches.
- Ordering matches.
- Filters match.
- Audio configuration matches where applicable.

### 4.5 Evidence

Automation should produce reviewable evidence when useful.

Examples:

```text
streamops/artifacts/
└── 2026-09-21_143000_gaming/
    ├── plan.txt
    ├── before.json
    ├── after.json
    ├── verification.json
    └── preview.png
```

Evidence is primarily local/generated data and should not automatically be committed unless useful for a review or debugging case.

### 4.6 Human approval

Codex may prepare and apply reversible setup changes, but destructive changes should be explicit.

Examples of destructive operations:

- Delete a scene collection.
- Remove an existing source not owned by StreamOps.
- Delete profiles.
- Replace user-created scenes.
- Overwrite unrelated OBS configuration.

---

## 5. OBS control model

OBS WebSocket is the primary control plane.

Recommended connection on A:

```text
Host: 127.0.0.1
Port: 4455
Authentication: enabled
```

Do not expose OBS WebSocket to the LAN unless there is a specific reason.

B should control OBS indirectly:

```text
B
↓ SSH
A
↓ StreamOps
OBS WebSocket @ 127.0.0.1:4455
↓
OBS
```

This keeps the OBS control endpoint local to A.

---

## 6. Repository layout

Current structure:

```text
StreamOps/
│
├── README.md
├── AGENTS.md
├── .gitignore
├── pyproject.toml
│
├── scripts/
│   └── local/
│
├── streamops/
│   ├── artifacts/
│   ├── assets/
│   ├── config/
│   │   ├── loader.py
│   │   └── scenes/
│   ├── docs/
│   ├── obs/
│   │   ├── client.py
│   │   ├── scene.py
│   │   └── transforms.py
│   ├── review/
│   │   └── service.py
│   ├── tests/
│   ├── __init__.py
│   ├── cli.py
│   ├── obs_client.py      # compatibility shim
│   ├── scene.py           # compatibility shim
│   └── transforms.py      # compatibility shim
```

The structure can evolve as the project grows.

Do not create abstractions prematurely.

---

## 7. CLI direction

The repository should expose a single command surface.

Target:

```powershell
streamops status
```

```powershell
streamops obs inspect
```

```powershell
streamops obs plan gaming
```

```powershell
streamops obs apply gaming
```

```powershell
streamops obs verify gaming
```

```powershell
streamops obs snapshot gaming
```

Eventually:

```powershell
streamops stream start
streamops stream stop
streamops stream status
```

and:

```powershell
streamops game status d4
streamops game start d4
streamops game stop d4
streamops game restart d4
```

B can invoke the same commands remotely:

```bash
ssh huy@192.168.1.8 'powershell -NoProfile -Command "streamops obs verify gaming"'
```

---

## 8. Codex agent responsibilities

Codex is an engineering agent, not the source of truth.

The repository is the source of truth.

For every meaningful change, Codex should:

1. Inspect the current repository state.
2. Inspect the relevant runtime state when necessary.
3. Understand the requested end state.
4. Update code/configuration.
5. Run tests.
6. Run a dry-run/plan when runtime state will change.
7. Apply the change when appropriate.
8. Verify the runtime result.
9. Capture useful evidence.
10. Summarize what changed.
11. Leave the repository in a reproducible state.
12. Update backlog/docs if new work is discovered.

Codex should not solve recurring tasks through one-off manual UI manipulation if they can reasonably be represented as code.

---

## 9. Backlog

The backlog belongs in both GitHub Issues and lightweight repository notes.

### GitHub Issues

Use GitHub Issues for actionable engineering work.

Suggested labels:

```text
area:obs
area:camera
area:steam
area:network
area:orchestration

type:feature
type:bug
type:automation
type:research
type:refactor

priority:p0
priority:p1
priority:p2
priority:p3
```

### Repository backlog

Use:

```text
backlog/todo.md
```

for small follow-ups discovered during active work.

Use:

```text
backlog/ideas.md
```

for ideas that are not yet specified enough to become GitHub Issues.

Do not allow `todo.md` to become a second full issue tracker.

---

## 10. Initial backlog

Recommended first milestones:

### Phase 0 — Baseline

- [ ] Create repository structure.
- [ ] Add `AGENTS.md`.
- [ ] Add Python project configuration.
- [ ] Add OBS WebSocket client.
- [ ] Load credentials from environment/local config.
- [ ] Confirm connection to OBS on A.
- [ ] Implement `streamops obs inspect`.

### Phase 1 — Read-only OBS inspection

- [ ] List scenes.
- [ ] List scene items.
- [ ] Read source/input settings.
- [ ] Read transforms.
- [ ] Read filters.
- [ ] Read current program/preview scene.
- [ ] Capture source/scene screenshots.
- [ ] Export normalized OBS state to JSON.

### Phase 2 — Desired-state scene automation

- [ ] Define scene YAML schema.
- [ ] Implement plan/diff.
- [ ] Implement scene creation.
- [ ] Implement input/source creation.
- [ ] Implement item transforms.
- [ ] Implement visibility and ordering.
- [ ] Implement idempotent apply.
- [ ] Implement verification.

### Phase 3 — Gaming scene

- [ ] Define `Gaming` scene.
- [ ] Add game capture.
- [ ] Add camera D.
- [ ] Configure camera placement.
- [ ] Configure audio.
- [ ] Generate preview evidence.
- [ ] Human acceptance.

### Phase 4 — Runtime operations

- [ ] OBS start/stop/status.
- [ ] Recording start/stop/status.
- [ ] Streaming start/stop/status.
- [ ] Health checks.
- [ ] OBS stats capture.
- [ ] Recovery commands.

### Phase 5 — Remote orchestration from B

- [ ] Stable SSH command interface.
- [ ] `streamops status`.
- [ ] One-command preflight.
- [ ] One-command stream start.
- [ ] One-command stream stop.
- [ ] Recovery workflow.

---

## 11. Configuration and secrets

Never commit:

- OBS WebSocket passwords.
- SSH private keys.
- API keys.
- Streaming keys.
- Platform tokens.
- Account passwords.

Use environment variables or ignored local files.

Example:

```text
.env
config/local.yaml
secrets/
```

These paths should be ignored by Git.

Commit example files:

```text
.env.example
config/obs.example.yaml
config/hosts.example.yaml
```

---

## 12. Runtime deployment

StreamOps runs in place from the current repository:

```text
C:\Users\huy\codex-work\StreamOps
```

Bootstrap the repo-local environment:

```powershell
.\scripts\devices\a-windows\install-streamops-node.ps1 -Dev
```

Run the Windows node in the foreground with an explicit port:

```powershell
.\.venv\Scripts\streamops.exe runserver --port 8785
```

Or manage it from the repository through an on-demand Scheduled Task:

```powershell
.\scripts\devices\a-windows\start-streamops-node.ps1 -Port 8785
.\scripts\devices\a-windows\status-streamops-node.ps1
.\scripts\devices\a-windows\stop-streamops-node.ps1
```

The task has no automatic trigger and uses the logged-on user's interactive token so
Windows screen capture runs on the active desktop. The start command verifies a real
captured frame before it reports success. DXGI is preferred; WinRT is used automatically
when the display driver initializes Desktop Duplication but does not deliver frames.
When the node binds to `0.0.0.0`, lifecycle health checks use the active LAN address so
an unrelated SSH listener on `127.0.0.1` cannot shadow the node.

Runtime state and `latest.png` are written only to `.streamops\node`. CLI flags override environment variables; supported variables are documented in `.env.example`.

To allow device B through Windows Firewall, run the bootstrap once from an elevated shell with `-ConfigureFirewall`. The rule is limited to the Private profile and local subnet.

The node serves a management dashboard at `/`, with Screen Capture at `/screen`
and Steam Management at `/steam`. It exposes:

```text
GET  /api/v1/health
POST /api/v1/screen/capture
GET  /api/v1/screen/latest
GET  /api/v1/steam/status
POST /api/v1/steam/restart
```

If the interactive Windows desktop is temporarily unavailable, health remains online with `capture_ready: false`; capture requests return `503` without replacing the previous successful image.

Steam status is read from the real Windows process and installation metadata. The
restart endpoint accepts no request body: it requests graceful shutdown, waits for the
old process to exit, then launches the resolved `steam.exe` with `-bigpicture` and
verifies a new process in the interactive desktop session. Concurrent restart requests
return `409`; shutdown timeout never force-kills Steam.

Existing commands in `C:\Scripts`, such as:

```text
steam-switch
internet-on
internet-off
```

remain valid.

StreamOps does not modify or replace them.

---

## 13. Safety rules

Automation must prefer reversible operations.

Before destructive changes:

- capture current state;
- identify ownership;
- make the proposed removal explicit.

Do not delete OBS resources just because they are not declared in a StreamOps scene specification.

By default:

```text
managed by StreamOps → may be reconciled
unknown/user-managed → preserve
```

This distinction is important because OBS may contain scenes or sources created manually for unrelated work.

---

## 14. Definition of done

An automation task is not complete merely because code was written.

For OBS-related changes, done means:

```text
code/config updated
        +
tests pass
        +
desired-state plan is correct
        +
change applied successfully
        +
runtime state verified
        +
preview/evidence reviewed when applicable
```

The final human decision remains with the operator.

---

## 15. Long-term direction

StreamOps can eventually become the control plane for the complete livestream stack:

```text
                      ┌───────────────┐
                      │      B        │
                      │ Android       │
                      │ Termux        │
                      └───────┬───────┘
                              │ SSH
                              ▼
                    ┌───────────────────┐
                    │        A          │
                    │ Windows           │
                    │                   │
                    │ StreamOps         │
                    │ Codex Agent       │
                    ├─────────┬─────────┤
                    │         │         │
                    ▼         ▼         ▼
                   OBS      Steam     Windows
                    ▲
                    │ camera
                    │
                    D
```

C remains the interactive remote gaming client:

```text
Xbox Controller
      ↓
C / Steam Link
      ↓
A / Game
```

The long-term operating model is:

> Human defines intent.  
> Codex prepares and executes reproducible automation.  
> StreamOps records the desired state.  
> APIs perform the actual changes.  
> Verification produces evidence.  
> Human accepts the result.
