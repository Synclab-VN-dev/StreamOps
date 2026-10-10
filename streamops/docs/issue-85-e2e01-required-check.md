# E2E-01 — Required Game CI status check

Current repository Ruleset **Master** is [#24454446](https://github.com/Synclab-VN-dev/StreamOps/rules/24454446),
`enforcement=active`, covering `~DEFAULT_BRANCH`. The status-check rule
currently has `strict_required_status_checks_policy=true` but
`required_status_checks=[]`. **This is not adequate merge protection.**

The `.github/workflows/tests.yml` Windows job now:
- Executes G1–G6, wheel HTTP/WS smoke, three repeat race tests and full regression for GameService changes.
- Always runs `Game E2E-01 — required gate audit`, even when a previous stage fails.
- Checks that game-relevant changes activated the GameService test scope.
- Asserts each G1–G6, wheel, race and regression outcome is `success`.
- Fails the `windows` job if any required stage is skipped, fails or is cancelled for relevant changes.

**One repository-admin setting is still needed** to prevent a PR from being merged
without the `windows` status check at all. GitHub's required check context is
the job name **`windows`**, not `Tests / windows`. The connector is a
GitHub App without administration-write access, even when the linked
collaborator is a repository admin.

From a PowerShell shell authenticated through `gh auth login` with
repository administration permission, execute:

```powershell
.\scripts\ci\ensure_game_required_ruleset.ps1
.\scripts\ci\ensure_game_required_ruleset.ps1 -Apply
```

The script validates it is changing Ruleset Master for the default branch,
preserves the other rules and bypass actors, appends `windows` and verifies
the persisted result. It never changes Steam, OBS or the game.

Alternative GitHub UI: **Settings → Rules → Rulesets → Master →
Require status checks to pass → Add checks → windows → Save changes**.
Keep strict/branch-up-to-date enforcement enabled.

After this setting is verified, `E2E-01` can be marked DONE. Before then,
do **not** equate a successful run with actual merge enforcement.
