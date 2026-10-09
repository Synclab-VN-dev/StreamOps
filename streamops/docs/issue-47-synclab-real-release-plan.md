# Issue #47 — Kế hoạch phát hành 2 release thật cho OBS Plugin Manager

> Plan only — 2026-10-09. **Chưa được publish release, chưa mutate máy A.**
> Managed repo: https://github.com/Synclab-VN-dev/StreamOps-OBS-Plugins
> StreamOps implementation: PR #52, backend contract của issue #47.

## 1. Mục tiêu và nguyên tắc

Nghiệm thu D12–D15 và D03–D08 bằng **hai phiên bản binary upstream có thật** trên GitHub Releases chính thức của Synclab, không fake số version, không dùng local fixture làm bằng chứng máy A.
Không tải trực tiếp upstream vào OBS khi test production: StreamOps **chỉ tải asset từ GitHub Releases managed của Synclab**.
Trên Windows A: OBS phải READY và WebSocket connected trước preflight; trước mỗi mutation phải xác nhận OBS không stream/record, có backup và SHA baseline.

**Ràng buộc của implementation hiện tại:** GitHubReleaseSource.latest(plugin_id) chọn **bản approved mới nhất**. Không có API install(version) tùy ý. Vì vậy cần **publish theo thứ tự**: v1 trước, Dev F install/verify v1, sau đó mới publish v2 và test update v1→v2. Nếu cả hai đã public sẵn, một máy A mới không thể install v1 qua Plugin Manager mà không thêm khả năng pin version/isolated source; không được lách bằng sửa version trong manifest.

## 2. Hai upstream candidates (phải kiểm tra compat trước khi approve)

| Candidate | Upstream release tag | Package filename | GitHub reported SHA-256 | Upstream published |
|---|---|---|---|---|
| v1 | sorayuki/obs-multi-rtmp @ 0.7.4.3 | obs-multi-rtmp-0.7.4.0-windows-x64.zip | 5fc2a14a4222cef914d4703325853b1f97247abe76bbd1fccd0dbd40831affe5 | 2026-08-01 |
| v2 | sorayuki/obs-multi-rtmp @ 0.7.4.4 | obs-multi-rtmp-0.7.4.4-windows-x64.zip | 39dffb45dc2a73db0d8777bde4baec2a8d61736577795e2c592ca0e2c0f6952b | 2026-10-02 |

Upstream: https://github.com/sorayuki/obs-multi-rtmp/releases

Source is GPL-2.0 per upstream repository metadata and LICENSE. Redistribute only after verifying obligations for binaries/source offer, copyright notices, license copy, modifications (none preferred), dependencies, and required attributions. The boolean approval flag alone is **not cryptographic provenance**.

**Blocker possibility:** v2 ZIP's actual OBS vendor DLL version/log may differ from the filename or may not support OBS 32.2.1. In either case do not invent an internal package version or override logs to obtain PASS; choose another real upstream build or rebuild from approved source with a reproducible recorded build process and matching semantically distinct version.

## 3. Release Readiness Gate (RG01–RG04)

**RG01 — nguồn gốc, license, binary compatibility**
1. Identify immutable upstream release/tag/commit and asset IDs; compute independent local SHA-256 and compare with upstream digests shown above.
2. Inspect ZIP paths against WindowsObsMultiRtmpInstaller allowlist, required DLL/PDB/locale, no symlink/path traversal/ZIP bomb.
3. Confirm actual DLL/plugin version, OBS 32.2.1 compatible, vendor `sorayuki.multi_rtmp` with `list_targets`, and UI ability to configure targets. The version used in manifest must equal actual loaded version.
4. Record GPL-2.0 notices/license and source-availability/provenance details; obtain required distribution approval.

**RG02 — canonical signed-off manifests/packages**
Prepare two independent approvals for:
- Synclab release tag `obs-multi-rtmp/v0.7.4.0` (upstream tag 0.7.4.3).
- Synclab release tag `obs-multi-rtmp/v0.7.4.4` (upstream tag 0.7.4.4).

Each GitHub Release must contain exactly one `obs-multi-rtmp.release.json` and the ZIP named by `artifact_name`. Manifest uses `PluginRelease` schema:
```json
{
  "plugin_id": "obs-multi-rtmp",
  "version": "0.7.4.0",
  "source_commit": "<actual upstream source commit SHA>",
  "platform": "windows",
  "architecture": "x64",
  "obs_version": "32.2.1",
  "artifact_name": "obs-multi-rtmp-0.7.4.0-windows-x64.zip",
  "artifact_sha256": "5fc2a14a4222cef914d4703325853b1f97247abe76bbd1fccd0dbd40831affe5",
  "vendor": "sorayuki.multi_rtmp",
  "metadata": {
    "approved": true,
    "redistribution_approved": true,
    "file_count": "<computed integer>",
    "relative_paths": ["<exact installed paths, sorted>"],
    "tree_sha256": "<computed SHA-256 from file-record manifest>"
  }
}
```
Values marked with angle brackets are placeholders, **not ready to upload**. Manifest `metadata.file_count` is an integer, not a string. Compute exact tree using `_file_records` / `_tree_digest` after extraction/mapping. v2 has its own manifest/version/artifact SHA/tree hash/source commit. Never use v1's file digest or status for v2.
If packaging manifest format is extended for additional evidence, keep source-compatible with current `PluginRelease` dataclass or version the contract first.

**RG03 — máy A, rollback & baseline**
Backup plugin files, OBS scenes/profiles, existing `obs-multi-rtmp.json` and transaction journal; save before SHA/config evidence. Avoid testing during stream/record. Use the existing OBS Process API for stop/start. Do not take ownership of unmanaged installation or overwrite user plugin files without a safe migration plan.

**RG04 — audit & immutability**
Publish assets from a reviewed GitHub Actions release workflow, require reviewer approval and restricted release-writing credentials; protect release tags and avoid editing published assets. Save upstream tag/commit, download SHA, Synclab release URL/tag/asset ID/SHA and publish actor. Check for download integrity from managed Synclab API on Win-A. Evidence contains no tokens/stream keys.

## 4. Thứ tự triển khai và nghiệm thu thật

1. **Build/validate candidate package**: Download upstream zips in an isolated build job; compare SHA; inspect ZIP & DLL; create manifest using pinned file records; verify license, source_commit and OBS 32.2.1 vendor compatibility. This step is preparation — no Synclab releases yet.
2. **Stage v2 as draft** (optional): Draft is ignored by `GitHubReleaseSource` so v1 remains latest. Do not publish v2 prematurely. Keep v2 artifact ready with provenance.
3. **Publish Synclab v1 as regular GitHub Release** `obs-multi-rtmp/v0.7.4.0`; verify `GET /api/v1/obs/plugins/available` sees v1 on A.
4. **Dev F: Install v1** on safe/baseline A. Run Plugin Manager Install → Process API Start/Restart → Vendor Verify PASS; capture DLL/config SHA, release URL/tag, GitHub asset ID, OBS logs and API evidence.
5. **Publish Synclab v2 as regular GitHub Release** `obs-multi-rtmp/v0.7.4.4`; validate catalog shows UPDATE_AVAILABLE (not silently replacing v1).
6. **Dev F: Update v1→v2** via Plugin Manager → Process API Start → Vendor Verify PASS; compare file/tree SHA, ensure targets/stream keys unchanged.
7. **Dev F: Rollback v2→v1** via API → Process API Start → Vendor Verify; compare v1 DLL/tree & configuration byte-for-byte; verify available catalog still correctly advertises v2.
8. **Dev F: Negative cases** using non-mutating preflight or isolated test source: repo empty/unavailable, missing asset/hash mismatch, active streaming/recording guard, wrong OBS version, no upstream fallback; no destructive injection into production assets. On failure, restore baseline.
9. **Operator UI review** (M01–M12), snapshot evidence, update checklists only for observed PASS.

## 5. Test result criteria, NOT READY / STOP conditions

- CI U01–U24 and E01–E17 green on current PR HEAD including source hardening.
- Two genuinely different, approved, hash-verified binaries: both run on OBS 32.2.1 and register vendor. If v2 does not, **STOP**.
- GitHub managed repo published assets are immutable, license/provenance documented. Release count was **0 on 2026-10-09** before implementation.
- D01 preflight + RG01–RG04 complete before any file changes on A.
- A failure to meet these criteria is `BLOCKED`, never auto-converted into PASS. PR remains Draft until review approval.

## 6. Tách trách nhiệm

- Automation: implement/test backend and CI; prepare release plan/artifact evidence and manifest builder separately.
- Release maintainer: approve license/compatibility, publish v1/v2 sequentially through reviewed workflow.
- Dev F: run Win-A preflight and install/update/verify/rollback with evidence, not via fake fixture.
- Operator: verify UI, targets and livestream safety.

**Current request authorizes this plan, not publication.**
