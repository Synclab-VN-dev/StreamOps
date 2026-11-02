# OBS plugin — current managed release policy (#166)

Updated by Owner decision 2026-11-02. The Issue #47 development-branch exception
is retired. Production publication is **trusted master + workflow_dispatch +
operation=publish** only. Same-repository write collaborators are trusted under
CI-CONTRACT.md; no malicious-writer isolation claim is made.

## Source, orchestration and regression ownership

- Source/product owner: `util/obs-multi-rtmp-websocket/`.
- Generic wrapper: `.github/workflows/main.yml` (no OBS test commands).
- Generic engine: `.github/workflows/ci.py` discovers `ci.test.py` (ID `obs-plugin`)
  and `ci.release.py` (ID `obs-plugin-release`). No component registry.
- `obs-plugin--regression`: isolated Python, release-policy and package-harness
  tests at `streamops/server/tests/test_obs_plugin_release_{workflow_policy,harness}.py`.
  Paths stay for existing StreamOps integration coverage; OBS owns their invocation
  and watches both test files plus the packager/installer/source dependencies.
- `obs-plugin--candidate`: existing Windows C++/DLL build and unapproved package
  verification, reusing the product implementation. No install/control of OBS.
- Packager/verifier: `scripts/release/obs_plugin_package.py`.
- Destination: `Synclab-VN-dev/StreamOps-OBS-Plugins`; exact buildspec version and
  OBS 32.2.1 compatibility are required.

## Publication sequence

1. Manual publish on master: validate intent/ref/version/OBS compatibility.
2. Build custom DLL, package candidate and reviewed payload from the same source.
3. Separate `external_publish` capability: `obs-plugin-release` environment and
   `SYNCLAB_OBS_RELEASE_TOKEN`, scoped to the distribution repository.
4. Revalidate same-run build report, artifact hashes, approved manifest, source
   commit, version and exactly four assets before exposing token to transport.
5. Refuse existing Release; create draft with four assets.
6. Download remote assets, byte-compare all four, then promote that draft.
   Failed verification must not promote. Never overwrite or rebuild during publish.

PR/push tests and manual build do not publish. Normal GITHUB_TOKEN has read-only
permissions in the external publish job; it cannot replace the distribution token.
No feature branch is authorized. Keep existing environment/token binding; this
refactor neither changes settings nor claims protection rules have been provisioned.

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

## Commands (documentation only; publication is not a test)

Local component regression, without building a Windows DLL:

```sh
python .github/workflows/ci.py run --component obs-plugin --job obs-plugin--regression --output /tmp/obs-regression
```

Build-only: manual main.yml, `operation=build`, `product=obs-plugin-release`,
`version=<exact buildspec version>`. Production manual intent:

```sh
gh workflow run main.yml --repo Synclab-VN-dev/StreamOps --ref master \
  -f operation=publish -f product=obs-plugin-release -f version=0.7.4.3
```

Do not execute publication during automated regression. Tests use temporary
synthetic packages, mocked installer probes and policy preflight; they do not
prove real OBS/native deployment acceptance. Historical RH/RG/Windows-A runtime
acceptance still requires its separately authorized environment and evidence.
No OBS/Steam/game operation, live Release write or settings change is part of #166.
