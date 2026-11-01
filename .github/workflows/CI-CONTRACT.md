# Component CI contract — streamops-ci/v1

Issue #166. Base: PR #164, `7148c404865b11d0e492f6159354f3312357b9dc`.

## Entrypoints and ownership

`main.yml` transports jobs, approved credentials and artifacts. `ci.py` discovers
`ci.test.py` and `ci.release.py` recursively from Git files. It reads one literal
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
PRs use merge-base; pushes use before/after. A verified new-branch push
(`created=true`, zero `before`, matching `after`/checkout HEAD) conservatively
selects all regular tests and records that reason; it never selects publishing
or manual trusted-fixture jobs. Zero `before` on other events remains blocked. Local `--changed` includes tracked
edits and nonignored untracked files. Contract metadata from both sides is examined.

Test jobs use operation `test`. Product jobs use `build` or `publish` and may declare
`release_tags`; unknown or ambiguous tag ownership fails closed. A publish plan
contains both build and publish jobs; changed files never imply publishing.

## Capabilities and trust

Profiles `linux` and `windows` select hosted ubuntu-24.04 and windows-2022.
Contracts cannot request self-hosted runners or choose an environment. Tool
versions are plain validated values, never interpolated as shell source.

| Capability | Operation | Wrapper policy |
|---|---|---|
| read | test/build | contents:read, no repository secrets |
| public-inputs | build | explicit dispatch/tag; optional approved public input URL/hash aliases; read token |
| fixture | manual test | dispatch on master, maxroll-fixture-trusted; exact age identity alias; read token |
| publish | publish | explicit dispatch or recognized tag, contents:write; verified same-run build |
| external-publish | publish | manual publish on master or feat/issue-47-obs-plugin-manager; obs-plugin-release; exact OBS release token |

Secret names/aliases are declarations, not grants. Engine validates the fixed
approved bindings; workflow supplies only those bindings in their execution step.
PR metadata cannot enable privileged jobs. No `pull_request_target` is used.
Credentials are omitted from plans, arguments and reports, and redacted from logs.
Build/test cannot import broad release credentials from the caller environment.
Local privileged execution additionally needs `CI_TRUSTED_EXECUTION=1` and explicit
credentials; this flag is a local preflight, not the GitHub authorization boundary.

Read-only inventory on 2026-11-01: `obs-plugin-release` exists with **no protection
rules**. `maxroll-fixture-trusted` was absent from the environments response.
Do not claim an approval gate exists merely from its YAML name. Provisioning and
changing protection rules remain Owner/admin work; no fixture run was performed.

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
Aggregate fails on missing, duplicate, wrong-source or non-PASS required reports.
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
consume `--inputs <downloaded same-run reports/artifacts>`. Local sequential
publish must also point `--inputs` to its build output. Build-only never checks
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
| obs-multi-rtmp-build / build | OBS test/product contract: DLL + unapproved package, no OBS install/control |
| obs-multi-rtmp-build / publish | OBS product contract: manual/ref/version/OBS pin, draft/four assets/roundtrip byte-compare/promote |
| d4planner-release / build/publish/UAT | product-root adapter reuses tools/release_ci.py; exact Setup integrity, stable/UAT policy, source-bound artifacts |
| d4planner-issue-log-cleanup | schedule wrapper + script/schedule.py, unchanged domain eligibility and revalidation |

HUD changes retain the historical StreamOps integration dependency; Launcher-only
changes do not select StreamOps. Logging shared by HUD and Launcher is explicitly
watched. Independent report-gateway selection does not imply local desktop startup.

## Maintenance

`schedule.yml` preserves cron `17 * * * *`, concurrency, 10-minute timeout,
contents:write/issues:read, and manual dry-run default. The Python script validates
trusted default-branch context, runs gateway mock tests, validates explicit IDs,
and calls the existing cleanup domain. Scheduled mode executes; manual mode
executes only for explicit dry_run=false. Local mode is dry-run only. Domain
CLOSED >24h, latest close, refetch/mapping/foreign/orphan protections are unchanged.
No live cleanup is part of CI tests. Reports contain source/mode/counts/exit/duration,
never credentials or diagnostic content.

## Local-first and handoff

Required selected suites must pass before push. An environment gap is BLOCKED,
not synthetic PASS; an exception to push requires Owner approval. Do not poll,
trigger or rerun Actions, publish, perform real cleanup, or change repository
settings as part of local verification. Runtime business code, visual references,
and release approval policy remain outside this refactor.
