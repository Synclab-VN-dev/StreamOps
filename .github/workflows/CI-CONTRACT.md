# Component CI contract — streamops-ci/v1

Issue #166. Base: PR #164, `7148c404865b11d0e492f6159354f3312357b9dc`.

## Entrypoints and ownership

`main.yml` transports jobs, approved credentials and artifacts. `ci.py` discovers
`ci.test.py`, `ci.release.py` and `ci.schedule.py` recursively from Git files. It reads one literal
`CI_SPEC` assignment through AST; planning never imports component code.
Execution invokes `run(context)` only after validating source and job identity.
There is no component registry in the engine or workflow. Release adapters belong
to product roots, including `utility/d4planner/ci.release.py`.

`main.yml` has a final job ID `result`, with check name **windows**. This deliberately
preserves the active Master ruleset's required context (ruleset 24454446,
integration 15368); it aggregates both OS profiles and is not a claim that Linux
results are Windows evidence. No ruleset mutation is part of this migration.

## Metadata v1

```python
CI_SPEC = {
    'version': 1, 'id': 'example',
    'watch': ['shared/schema/**'], 'depends_on': ['shared-contract'],
    'jobs': [
        {'id': 'unit', 'profile': 'linux', 'timeout': 300},
        {'id': 'native', 'profile': 'windows', 'timeout': 900,
         'tools': {'node': '22', 'rust': '1.90.0'}},
    ],
}
def run(ctx):
    ctx.python('-m', 'unittest', 'discover', '-s', 'example/tests')
```

IDs are globally unique. Dependencies must exist and be acyclic. `depends_on`
propagates affected tests transitively; it is not a build ordering mechanism.
Jobs prepare their own dependencies. Nearest test-contract folder owns files;
`watch` adds cross-folder coverage. Explicit `ignore` patterns document paths
with no source verification requirement. Unknown paths, removed contracts without
replacement coverage, missing history, malformed metadata and unsupported runner
profiles fail closed. Rename detection examines both deleted and added paths.
PRs use merge-base; master pushes use before/after. A verified initial master push
(`created=true`, zero `before`, matching `after`/checkout HEAD) conservatively
selects all regular tests and records that reason; it never selects publishing
or manual trusted-fixture jobs. Zero `before` on other events remains blocked. Local `--changed` includes tracked
edits and nonignored untracked files. Contract metadata from both sides is examined.

Test jobs use operation `test`. Product jobs use `build` or `publish`. Every declared
job is required; schema v1 rejects the `required` field (including `required:false`).
A publish plan contains both build and publish jobs; changed files never imply
publishing. Tag-triggered release metadata and channel selection are removed.

## Capabilities and trust

Profiles `linux` and `windows` select hosted ubuntu-24.04 and windows-2022.
Contracts cannot request self-hosted runners or choose an environment. Tool
versions are plain validated values, never interpolated as shell source.

| Capability | Operation | Source wrapper policy |
|---|---|---|
| read | test/build | contents:read, no repository secrets |
| public-inputs | build | explicit dispatch; optional public input URL/hash aliases; read token only |
| fixture | manual test | dispatch on master, maxroll-fixture-trusted; exact age identity alias |
| publish | publish | manual publish on master; job-scoped contents:write GITHUB_TOKEN; verified same-run build |
| external-publish | publish | manual publish on master; obs-plugin-release environment; exact OBS release token |
| maintenance | schedule | schedule/manual on trusted default branch; contents:write + issues:read; exact maintenance token/config bindings; local dry-run only |

Secret aliases request capability; they never grant it. Source checks validate
operation, master ref, dispatch inputs/product/version and source SHA before binding
publish credentials or importing the contract. Missing credentials block execution.
The executor strips inherited credential variables from read/build subprocesses.
Plans/matrices contain names only; bound secret values are redacted from evidence.
`CI_TRUSTED_EXECUTION=1` is defense in depth, not an authorization boundary. Local
production publishing is blocked: production requires GitHub manual master context.

### Threat model — Owner decision 2026-11-02

Development stays on same-repository feature branches. Write collaborators,
including `synclab-automation-system`, are trusted. Deliberately malicious or
compromised write collaborators modifying workflow/engine source are outside
acceptance #166. No fork migration or independently enforced permission ceiling
is required. Repository read defaults are not claimed to impose such a ceiling.

F1 is PARTIALLY_AGREE / FIX_REQUIRED for intended-flow isolation; the prior
adversarial-YAML/admin-provisioning blocker is superseded by this Owner decision.
CI-11 now verifies that the reviewed workflow and engine reject accidental or
metadata-driven escalation: PR/read and manual build do not receive production
write capability; production requires manual master publish plus exact intent,
source and artifact validation. Static metadata can request capability but only
the reviewed workflow grants it. No `pull_request_target` is used.

The workflow defaults to contents:read. Only the production publish job requests
contents:write and supplies its ephemeral GITHUB_TOKEN to the publish executor.
It runs after build jobs; the executor/product verifier revalidate same-run
source/version/checksum before any Release mutation. No new PAT, production
Environment, admin provisioning or deployment-review step is required. Missing
token still fails closed. Owner review/merge and manual publish are the intended
authorization, not a defense against a trusted writer intentionally rewriting it.

Historical read-only inventory found only obs-plugin-release with no branch
policy/protection, and repository workflow permissions default read. No settings
were changed. Existing external OBS and fixture credentials remain separate;
their live execution/provisioning is not exercised or claimed by this change.

## Owner flows

- Development: local test → pull_request CI → Owner review/merge → master push CI.
  Feature pushes do not run an additional push CI; no tag triggers.
- Test installer: workflow_dispatch `operation=build`, product and explicit version
  → build/verify → Actions artifact → Owner download/install/test. No GitHub Release,
  production credential, or Release-existence check. UAT is testing an artifact.
- Production: trusted master + workflow_dispatch `operation=publish`, product/version
  → build/verify → job-scoped write token → stable GitHub Release.
  No extra deployment review is prescribed. Manual versions are validated, never inferred from a tag.

## Execution and evidence

Each job gets an owned temporary checkout, venv when requested, temporary paths,
logs and output directory. Old native harnesses may detach that owned checkout;
the caller's branch/worktree is never changed. The checkout includes the selected
local dirty source bytes. Test cleanup removes only owned resources.

Commands have bounded time, subprocess-tree timeout/cancellation cleanup and
recorded exit codes/durations. Result records source HEAD/tree (dirty snapshots
are SHA-256), plan ID, job, OS, commands, parsed test counts, artifacts and hashes.
Artifact hashes and build report source/plan identity are revalidated before
publishing. Product verifiers additionally enforce version/source/resource policy.
Logs and diagnostics are not substitutes for independent native/visual evidence.

`PASS`, `FAIL`, `BLOCKED`, `NOT_RUN`, `CANCELLED`, and `NO_CHANGE` remain distinct.
Aggregate fails on missing, duplicate, wrong-source or non-PASS reports (all declared jobs are required).
Only a successfully validated empty plan can produce NO_CHANGE. The final check
also requires planner success; skipped or cancelled jobs cannot manufacture PASS.

```sh
python .github/workflows/ci.py plan --base <BASE_SHA> --head <HEAD_SHA> --output /tmp/ci-plan
python .github/workflows/ci.py run --changed --output /tmp/ci-local
python .github/workflows/ci.py run --changed --component ci-engine --output /tmp/ci-engine
python .github/workflows/ci.py run --plan /tmp/ci-plan/plan.json --job <ID--JOB> --output /tmp/ci-results
python .github/workflows/ci.py run --product d4planner-release --operation build --version 1.2.8 --output /tmp/ci-build
```

Outputs must be outside the repository. A saved plan binds exact source; modifying
source requires a new plan and relevant reruns. `--changed` is required to select
uncommitted contract edits; otherwise planning reads committed HEAD. A missing
Windows runtime is BLOCKED on Linux. Do not start a VM implicitly.

Publish interface: `run --product <ID> --operation publish --version <VERSION>`.
This documents the command, not authorization to release. Separate publish jobs
consume `--inputs <downloaded same-run reports/artifacts>`. Local production publish is blocked; mocked transport tests exercise verification. Build-only never checks
Release existence. Publish refuses an existing version through the existing core.

## Migration ledger

| Previous workflow/job | Owning contract / retained verification |
|---|---|
| tests / d4planner-portability | BE portability + report-gateway mocked contract; same Python CLI/controller cases |
| tests / Windows Launcher | Launcher native cargo test/build, Rust 1.90 |
| tests / D4Planner runtime | BE native: full tests, Node packages, wheel, NVDA artifact, all issue87 negative/preflight gates |
| tests / StreamOps G1–G6 | streamops native: full regression, installed wheel, 3 race runs, negative guard and always-run gate audit |
| tests / FE-G1/2/3/4/6 | streamops native: original targeted browser/WS/lifecycle/wheel commands |
| tests / PR89 special safety harness | scripts/acceptance contract: same SelfTest and expected-BLOCKED smoke, no Host A task/runtime |
| d4-overlay-poc / windows-exe | HUD native: React, Rust logging/report/Tauri, portable EXE and real GUI smoke/artifact |
| d4-rulekit / schema | Rule Kit schema: positive/negative fixtures, execution vectors, wheel outside checkout |
| d4-rulekit / browser, provider, application | Rule Kit jobs: locked npm, pinned browser, unit/type/contract/offline synthetic E2E and reports |
| d4-rulekit-maxroll-real | Rule Kit explicit encrypted-fixture job: age checksum, ephemeral key, offline acceptance, sanitized four files |
| game-manager-visual | nested visual contract: independent reference builds, immutable hashes, enforced approval and screenshot/diff evidence |
| obs-multi-rtmp-build / build | obs-plugin candidate: unchanged Windows DLL + unapproved package verification; no OBS install/control |
| StreamOps OBS policy/package regressions | obs-plugin regression: Linux job invokes existing policy + harness suites; watches both tests/packager/installer/source; StreamOps full suite retains integration coverage |
| obs-multi-rtmp-build / publish | OBS product contract: explicit manual master-only/version/OBS pin; retired development-branch exception; draft/four assets/roundtrip byte-compare/promote |
| d4planner-release / build/publish | product-root adapter reuses tools/release_ci.py; exact Setup integrity; manual test artifact and stable publication are separate; legacy UAT Release removed |
| d4planner-issue-log-cleanup | schedule.yml → ci.py → Report Gateway ci.schedule.py → cleanup.py; centralized implementation removed, domain eligibility/revalidation unchanged |

HUD changes retain the historical StreamOps integration dependency; Launcher-only
changes do not select StreamOps. Logging shared by HUD and Launcher is explicitly
watched. Independent report-gateway selection does not imply local desktop startup.

## Component-owned maintenance — superseding Owner decision 2026-11-02

The taxonomy is now:

| Contract file | Responsibility / selection |
|---|---|
| ci.test.py | Component test/regression commands; --component ID |
| ci.release.py | Product build/verify/publish semantics; --product ID |
| ci.schedule.py | Component maintenance orchestration; --schedule ID |

There is one generic engine. Schedule kind is inferred from the filename; metadata
remains literal schema version 1. IDs are unique across all three kinds. Example:

```python
CI_SPEC = {'version': 1, 'id': 'example-maintenance', 'jobs': [
    {'id': 'audit', 'operation': 'schedule', 'capability': 'maintenance',
     'profile': 'linux', 'timeout': 600},
]}
def run(ctx):
    # Component owns context/config/preflight/domain invocation and public audit.
    ...
```

No cron/owner registry, arbitrary permission/environment/secret field or speculative
metadata is added. Schedule jobs require the reviewed maintenance capability;
other kinds cannot request it. Unknown fields/secret bindings fail closed. Common
tool/profile fields retain their existing validation/bootstrap semantics. The
manual-only job flag is invalid for schedule contracts: every schedule contract
participates in the shared hourly trigger and is available for manual selection.

Schedule planning only parses AST. `actions-plan --operation schedule` discovers
all schedule contracts (or the manual input ID); `--all --operation schedule` is
the equivalent explicit local planning selection. PR changed-file planning selects
the owning **test** contract; it never executes maintenance. Deleted/renamed
contracts use the existing ownership/uncovered-change rules; explicit stale IDs
fail closed. Existing source/contract identity, owned checkout, timeout for child
commands, redaction, artifact manifests and required-report aggregation are reused.

`main.yml` and `schedule.yml` remain the only workflows. `schedule.yml` plans a
dynamic maintenance matrix and calls `ci.py run`, then `ci.py aggregate`. It owns
only trusted event/ref/capability transport, runner bootstrap and artifact upload.
New contracts using the approved capability require no wrapper/engine registry edit.

### Context and credential policy

- Cron stays `17 * * * *`; concurrency group is retained across cutover.
- Scheduled event: execute after context/config/preflight checks.
- Manual: dry_run defaults true; false must match the dispatch payload.
- GitHub context must be schedule/workflow_dispatch on the event repository's
  default branch (master here), with checkout SHA matching GITHUB_SHA.
- Local: dry-run allowed; execute BLOCKED before importing the contract.
- Contract requests maintenance; the reviewed wrapper grants **contents:write,
  issues:read**, passing github.token as CI_MAINTENANCE_TOKEN. Context exposes it
  as GITHUB_TOKEN only to maintenance. Read/build jobs never inherit this token.
- Wrapper binds vars.D4PLANNER_DIAGNOSTIC_RELEASE_ID → DIAGNOSTIC_RELEASE_ID and
  vars.D4PLANNER_DIAGNOSTIC_BOT_ID → DIAGNOSTIC_BOT_ID. These are reviewed config
  bindings, not arbitrary metadata-selected variables/secrets. Engine knows neither
  config name nor cleanup domain. No settings/secrets were provisioned here.
- Same-repository trusted-writer threat model still applies. Contracts cannot grant
  themselves GitHub permissions; no claim is made against deliberate writer sabotage.

### Report Gateway owner and local parity

Owner: `utility/d4planner/d4planner-be/report-gateway/ci.schedule.py`, ID
`report-gateway-maintenance`. It validates context, runs business tests
`test_reports.py` without credentials, validates positive release/bot IDs and token,
then calls cleanup.py. Eligibility, CLOSED >24h/latest close, refetch/mapping,
foreign/orphan and delete semantics remain exclusively in cleanup.py. Only public
counts go into maintenance.json, which is attached to the generic result/evidence.
The orchestration tests run via the owning ci.test.py; preflight avoids recursively
invoking its own engine-integration test. The centralized schedule implementation
has been deleted without a compatibility shim.

```sh
python .github/workflows/ci.py run --schedule report-gateway-maintenance --dry-run true --output /tmp/maintenance
```

For a real read-only inspection the operator explicitly supplies
CI_MAINTENANCE_TOKEN and the two diagnostic IDs; missing configuration blocks.
This refactor's tests instead inject mocked transport through the **same run(ctx)**
and generic executor, exercising local dry-run/report/aggregate without production
credentials or network mutation. Local real cleanup is never authorized by a flag.

CI-01: two wrappers, component ownership. CI-02: zero-registry schedule onboarding.
CI-03: static metadata/negative validation. CI-07: common executor/local parity.
CI-11: reviewed maintenance capability/grants. CI-13: cron/modes/domain preserved.
CI-14: onboarding and synthetic/mock regression evidence. Actual cleanup is NOT_RUN.

## Local-first and handoff

Required selected suites must pass before push. An environment gap is BLOCKED,
not synthetic PASS; an exception to push requires Owner approval. Do not poll,
trigger or rerun Actions, publish, perform real cleanup, or change repository
settings as part of local verification. Runtime business code, visual references,
and release approval policy remain outside this refactor.

## OBS regression ownership — Owner update 2026-11-02

`main.yml → ci.py → util/obs-multi-rtmp-websocket/ci.test.py → regression suites`.
The wrapper transports event/capability/credentials/artifacts only. OBS policy
and packaging tests stay at their existing StreamOps test paths, but their explicit
Linux invocation belongs to `obs-plugin--regression`. The native candidate job
remains separate and unchanged; a regression-only local result does not claim the
Windows candidate passed. No component/path registry was added to the engine.

The previous policy assertion requiring a development ref was stale. It is replaced
by master-only wrapper assertions and executable product preflight negatives for
PR/push/feature/tag/build intent, exact version and OBS compatibility. Existing
manifest/provenance/installer/tamper and draft/four-assets/roundtrip assertions stay.
CI-02/07 cover owning invocation, CI-10 coverage preservation, CI-13 OBS cutover,
and CI-14 the updated contract/migration evidence. No live publication is a test.
