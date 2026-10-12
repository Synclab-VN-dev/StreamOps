# Issue #86 / PR #89 — Windows A + Android B acceptance

This is the **read-only** acceptance harness for [ticket #86](https://github.com/Synclab-VN-dev/StreamOps/issues/86), independent of real Steam/Diablo IV lifecycle. It follows `Library/OpenStream/rules/Common DEV rule.md` (Mandatory UAT Automation and Mandatory Approval Request) and `PR manual test port rule.md`.

## Before asking Owner to run UAT — What / Who / How

**WHAT:** Verify *isolated* PR #89 node on Windows A, then collect read-only Steam/Games WebUI route/asset and WS response evidence. This **does not** prove real GUI behavior or trigger two-observer changes in a running game. Remaining real A/B and visual checkpoints stay BLOCKED until observed. No real Steam/game Start/Stop/Restart authorized.

**WHO:** Automation or Dev F prepares, runs CI SelfTest and verifies runner revision; Owner only runs the script on A when asked and sends its `report.json` + `runner.log`, or performs device-specific/manual checks. CI evidence can be attached without requiring Owner to repeat it.

**HOW:** First prepare an isolated PR #89 worktree. Do **not** replace default Steam/OBS/StreamOps sessions. Only after reviewing preflight, an isolated PR89 node may be started via the already-established Windows A task workflow **with separate owner approval as needed**. The script never creates, starts or stops a task or service.

## Automated coverage

| Mode | Performed | Cannot pass |
| --- | --- | --- |
| `SelfTest` | Synthetic PASS/FAIL/BLOCKED/SKIP reports, JSON roundtrip, collision PID guards, safety audit | Any A/B acceptance |
| `Preflight` (default) | Current local git branch/HEAD; Windows, interactive console; expected task/arguments; DataDir/runtime; port 18789 and PID ownership. No HTTP/WS calls | Real A functionality, Android B visuals |
| `ReadOnly` | All preflight checks, HTTP GET `/steam`, `/games` and needed JS/CSS; two simultaneous `games.list` WS readers + read-only `steam.status` WS | Gameplay state changes, mobile interaction, OBS disconnect tests, real lifecycle |

The script is **fail-closed**: wrong HEAD/branch, missing/misconfigured isolated task, missing/mismatched runtime PID, occupied port or missing Windows session results in `BLOCKED`. It **never** kills a process, registers/starts/stops a task, installs Python/node packages, calls a mutating WS command, shuts off networking/OBS or changes a game state.

**Port:** `18789`; **Task:** `StreamOps-PR89-Manual`; **DataDir:** `.streamops/pr89/node`; **branch:** `feat/86-game-manager-ws-ui`. Runtime must be prestarted in that isolation; the harness does not create it.

## One-shot commands (Windows A PowerShell 7, from PR #89 worktree)

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\acceptance\issue86-pr89-uat.ps1 -Mode Preflight
```

Only when isolated preflight requirements have been met, execute read-only probes:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\acceptance\issue86-pr89-uat.ps1 -Mode ReadOnly
```

If using the **downloadable CI UAT artifact**, extract its `package/` folder anywhere on A. The script accepts `-WorktreeRoot` to identify the actual isolated PR89 worktree even when the script is in Downloads:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\package\issue86-pr89-uat.ps1 -Mode Preflight -WorktreeRoot "C:\Workspace\StreamOps-PR89-UAT" -ExpectedHead "<PR-HEAD-SHA>"
```

Replace the sample worktree path with the **actual** PR #89 checkout and the placeholder with the current CI-verified 40-character HEAD. The runner refuses an unrelated branch/head and does not check out branches automatically. After preflight confirms that a separately approved isolated task is running, replace `Preflight` with `ReadOnly` for the read-only transport smoke.

Pass `-ExpectedHead <40-character SHA>` to require the exact tested HEAD. **Always obtain the SHA from the current PR before running.** Runner outputs in the temp directory under `StreamOps-I86-UAT/<timestamp>-pr89/`: `report.json`, `summary.txt`, `runner.log`. Exit code: 0 = all executed checks PASS with no BLOCKED; 1 = FAIL; **2 = BLOCKED** (e.g. real-host checks not yet authorized). The intentional BLOCKED exit is not proof of a product failure. Do not paste credentials, session keys or unredacted private material into GitHub.

## What remains manual and therefore BLOCKED

- `DEVF-01`: browser-level confirmation on A; `ReadOnly` only proves transport/asset subchecks.
- `DEVF-02`: two real browsers on A/B receive changes pushed following an **authorized external state transition**, without polling.
- `DEVF-03`: real disconnect/reconnect, Windows-session mismatch, game external exit, OBS configured-only vs verified active, Steam stopped/game independent.
- `DEVF-04`: Android B navigation/touch/focus/safe-area, live viewport screenshots and approved MagicPath parity.
- `DEVF-05`: **explicit approval required** for Start/Stop/Restart Diablo IV or Steam. Unapproved stays BLOCKED.
- `DEVF-06`, `MAN-01..05`: final evidence consolidation and owner visual/behavior acceptance on actual A/B, not copied from CI.

## Runner verification and revision reporting

GitHub `Tests / windows` includes a dedicated step running `SelfTest` and the **negative Preflight** on an ordinary GitHub Windows runner; the latter must report `BLOCKED`, never falsely PASS. This proves the runner's *harness* behavior, not that it can reach A; actual `ReadOnly` with A's real WS protocol remains unverified until a safe isolated test there.

When changing this runner, add a short issue/PR revision comparison with: previous root cause, code changed, proven improvement, still unverified, tests run, expected next owner output. Do not send Owner a new script on the basis of static checks alone.

**Safety / scope:** No merge, release, GitHub Ruleset changes, deployment or real lifecycle action is authorized by this harness. PR #89 remains Draft until separate owner decisions.

## Preflight incident — 2026-10-11, Windows A report

Earlier runner output: `PRE-HEAD BLOCKED git HEAD unavailable`, `PRE-DATADIR / PRE-TASK / PRE-PORT BLOCKED`; summary `PASS=2 FAIL=0 BLOCKED=15`. This is an **environment-not-prepared** result, not a product failure. The path `C:\Workspace\StreamOps-PR89-UAT` was an **example**, not a preconfirmed checkout on Host A.

**Runner revision improvement (v3):**
- Previous limitation: catch-all Git HEAD error did not distinguish missing worktree, an existing non-Git folder, unavailable Git, bad branch or mismatched commit.
- Revised: classify exact input path before Git commands; shallow, **read-only** discovery of existing PR89 checkouts in `C:\Workspace` and `%USERPROFILE%\codex-work`; list candidates in `report.json` and a `PRE-WORKTREE-CANDIDATES` result. **No automatic branch checkout or runtime startup.** Added missing-directory/non-Git negative-path SelfTests.
- Evidence: [#89 Windows CI](https://github.com/Synclab-VN-dev/StreamOps/pull/89/checks) must PASS the new packaged runner SelfTest and negative Preflight on the **new HEAD** before this revision is given to the owner.
- Unverified: the owner-specific actual path, creation of PR89 worktree, Windows task/DataDir/runtime setup, live HTTP/WS on A, Android B interactions. None may be inferred from CI.
- Targeted next run: `-Mode Preflight` **only**; no need to repeat previously successful CI product/visual tests. If a candidate is found, use that path only after matching branch and exact HEAD; if none is found, the isolated PR89 worktree must be separately prepared. Any occupied port stays protected.

