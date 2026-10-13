# Issue #47 — Synclab custom OBS plugin: single-workflow managed release

> Release policy (2026-10-10): one existing GitHub Actions workflow owns build,
> package and publication. PR/push **never** publishes. Release requires an
> explicit manual dispatch with `publish_release=true` and a protected
> environment approval. PR #52 remains Draft until real-A acceptance is complete.

## Source and target

- Source: `Synclab-VN-dev/StreamOps/util/obs-multi-rtmp-websocket` (C++ custom
  `sorayuki.multi_rtmp` WebSocket Vendor support, `list_targets`).
- Existing build workflow: `.github/workflows/obs-multi-rtmp-build.yml`.
  This file already exists on default branch `master`, so GitHub can dispatch
  the PR #52 version via `--ref feat/issue-47-obs-plugin-manager`.
- Packaging and strict verifier: `scripts/release/obs_plugin_package.py`.
- Distribution only to `Synclab-VN-dev/StreamOps-OBS-Plugins`, via its GitHub Releases.
- Current v1 source: `buildspec.json` version `0.7.4.3`, built for OBS 32.2.1 Windows x64.
- No upstream ZIP relabeling, arbitrary asset URL, non-reviewed artifact, or
  dependency on merging the still-unaccepted Plugin Manager backend.

## Single workflow and event policy

```text
PR/push event
  → Windows build
  → package UNAPPROVED candidate + SHA/manifest/provenance/license
  → upload Actions artifact
  → FINISH (no release secret or publish job)

Manual workflow_dispatch, publish_release=false (default)
  → same build/package candidate
  → FINISH (no release secret or publish job)

Manual workflow_dispatch, publish_release=true, expected_version=VERSION
  → Windows build
  → package unapproved CI candidate and approved reviewed payload from same build
  → validate source/buildspec version and OBS 32.2.1 compatibility
  → verify ZIP/files/manifest/provenance/license/source commit/SHA
  → protected environment obs-plugin-release (required reviewer)
  → download exactly approved candidate into independent publish job
  → verify again BEFORE release credential is exposed
  → create DRAFT with exactly 4 assets in Synclab distribution repository
  → redownload and byte-compare 4 remote assets
  → promote same draft to published without rebuilding
  → final GitHub Release becomes discoverable by Plugin Manager
```

The `publish` job is explicitly gated by `github.event_name ==
'workflow_dispatch' && inputs.publish_release == true`. Both production
`master` and the explicitly reviewed `feat/issue-47-obs-plugin-manager`
branch are allowed; all other refs are blocked. The `windows-build` job never
receives the cross-repository release token. Secret only exists in the last
publish step, after environment approval and independent byte verification.
A failed upload/compare leaves a **draft**, not a visible release. Existing
tags are never overwritten.

The older `obs-plugin-managed-release.yml` and
`obs-plugin-promote-release.yml` workflows are superseded and removed from
this branch. Do not dispatch them.

## Artifact contract

Packager takes CMake Windows release tree at
`util/obs-multi-rtmp-websocket/release/RelWithDebInfo/obs-multi-rtmp/`:

- `bin/64bit/obs-multi-rtmp.dll` and `obs-multi-rtmp.pdb`
- `data/locale/en-US.ini` and allowed additional locale INI files

Published GitHub Release tag: `obs-multi-rtmp/vVERSION`, containing exactly:

1. `obs-multi-rtmp-VERSION-windows-x64.zip`
2. `obs-multi-rtmp.release.json`
3. `obs-multi-rtmp.provenance.json`
4. `LICENSE-GPL-2.0.txt`

ZIP paths, file count/tree SHA-256, artifact SHA-256, DLL SHA-256, source
commit, version, platform/arch, OBS compatibility and GPL/license metadata
must agree. Candidate packages mark `approved=false`; only an authorized
manual release request creates `approved=true` metadata. SHA/provenance
are checksums and traceability, not cryptographic signatures.

## One-time repository protection (operator/admin)

1. StreamOps → Settings → Secrets and variables → Actions: configure
   `SYNCLAB_OBS_RELEASE_TOKEN`, a least-privilege fine-grained token with
   Contents read/write **only** on `Synclab-VN-dev/StreamOps-OBS-Plugins`.
   Normal StreamOps `GITHUB_TOKEN` cannot write this other repository.
2. StreamOps → Settings → Environments: configure `obs-plugin-release` with
   *required reviewers* and restricted deployment branches. During PR #52
   release acceptance, allow the exact reviewed feature branch; for later
   releases, narrow this to `master`. A bare environment without rules is
   NOT an adequate production publication gate.
3. Protect distribution release/tag `obs-multi-rtmp/v*`, restrict asset
   deletion/replacement and review GPL redistribution/source availability.
4. Review custom C++ source and real OBS 32.2.1 Vendor API behavior on an
   isolated test system before approving each release.
5. Never check tokens into repo, workflow output, or test logs.

## Commands

**Build only from PR #52** (never publish):

```powershell
gh workflow run obs-multi-rtmp-build.yml `
  --repo Synclab-VN-dev/StreamOps `
  --ref feat/issue-47-obs-plugin-manager
```

**Manually build and request publication of reviewed v1** (publish waits at
environment approval, no automatic PR publication):

```powershell
gh workflow run obs-multi-rtmp-build.yml `
  --repo Synclab-VN-dev/StreamOps `
  --ref feat/issue-47-obs-plugin-manager `
  -f publish_release=true `
  -f expected_version=0.7.4.3
```

Check run details and verify release in the target repository:

```powershell
gh run list --repo Synclab-VN-dev/StreamOps `
  --workflow obs-multi-rtmp-build.yml `
  --branch feat/issue-47-obs-plugin-manager --limit 5

gh release view 'obs-multi-rtmp/v0.7.4.3' `
  --repo Synclab-VN-dev/StreamOps-OBS-Plugins
```

The release operation must not be triggered until environment protection,
license review, source review and token permissions are checked. A run may
produce a candidate artifact yet leave publication blocked if the reviewer
does not approve or the token is missing.

## Release-gate and real-A acceptance sequence

1. RH01–RH03: Windows source build, package, tamper detection and
   installer compatibility tests PASS on exact branch SHA.
2. RH04/RH05 are **one manual run** with separate protected `publish` job:
   source build, create draft, verify remote bytes, publish approved release.
   No second dispatch required.
3. RG01: published v1 `0.7.4.3` has valid manifest/provenance/SHA and
   is discoverable from A. Verify read-only `/api/v1/obs/plugins/available`.
4. D03–D05: with A backed up, OBS outputs idle, maintenance authorized,
   install v1 through Plugin Manager API (never manually replace plugin DLL),
   restart OBS through Process API and verify vendor `sorayuki.multi_rtmp`.
5. Only after v1 installation/verification, implement **real** v2 with
   source code changes, distinct source commit/version and distinct DLL SHA,
   then use same manual workflow to publish v2.
6. D06–D08/D14: update v1→v2, byte-compare config, verify vendor, test
   rollback and recovery in a safe isolated/approved window.
7. D09/D15 negative tests must fail closed and preserve output/file hashes.

**STOP** if environment protection or token policy is absent, source
commit/version/ZIP hashes differ, real Vendor API fails, existing release tag
exists, license source-availability requirements are unmet, or maintenance
approval/backup on Windows A is missing.
