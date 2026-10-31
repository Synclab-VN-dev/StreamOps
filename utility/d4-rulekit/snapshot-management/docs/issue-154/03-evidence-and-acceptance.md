# Evidence Phase 1 và acceptance sau design approval

## Evidence thực sự đã thực hiện

Source audited: `fd87a98325b36f3fd8931af217155643484a5c87`. Private offline analysis ngày 27/10/2026 trên Linux F; không capture, không truy cập Maxroll online, không sửa guard/profile, không dùng test registry để activate production.

r03 ciphertext `ci-bundle-20261027-r03.zip.age` SHA-256 `43e4926774e83a89476f4da74f0f27e440fd229c8ef4ec44ca2309070fe5e481` được giải mã bằng **existing `withDecryptedFixture`**, recipient/manifest/blob verification hiện hành. Baseline D12 đọc từ private store và verify lại toàn bộ. Plaintext extract tạm của r03 được xóa trong finally; snapshot gốc private giữ nguyên. Private identity không đọc/in/commit/upload.

| Check | Expected | Actual | Classification |
|---|---|---|---|
| D12 integrity | Exact manifest + all blobs | `638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54`, store verify PASS | PASS integrity |
| Dfjs integrity/decrypt | Exact r03 manifest + all blobs | `823839198d5b7f5c4621664c44e62da50d50af86baed577ddc3ec22d04b67819`, 371 resources / 369 blobs, PASS | PASS integrity |
| Parse engine JS | Không syntax diagnostic | D12/Dfjs: 0 diagnostics (TypeScript JS parser 5.9.3) | OBSERVED, không equivalence proof |
| Catalog | So actual bytes | Cùng SHA `889facd9fa21a0a2baba3f8c28d53ac66b6e28a7514994f82ab8f00a3a5e1f93` | REUSABLE data bytes |
| Option enumeration | So IDs từ exact engine bytes | 1.369 unique IDs cả hai, added=0/removed=0; set SHA `4ab94bc90a3a1c23614cd2d6cc8729100c6de6726744b0019f0b020835c0e6c8` | REUSABLE ID inventory; semantics UNVERIFIED |
| Engine module surface | So export alias inventory | Một export alias ở mỗi engine, set hash bằng nhau | OBSERVED, không proof ABI đầy đủ |
| Fresh Chromium | Offline transport trước navigation, no egress, cleanup | Hai probes độc lập: 0 CDP external egress completed, stopped/pid=null/leases=0 | PASS isolation/cleanup |

## Before → Current runtime observation

Tọa độ dưới đây là **CDP zero-based**. Token shape hash thay identifier token bằng marker, giữ token kind/literal; đây là heuristic tìm điểm quan sát để kiểm tra bằng CDP, không được dùng làm compatibility decision hay tắt guard.

| Observation | D12 | Dfjs | Kết luận giới hạn |
|---|---|---|---|
| Engine | export-D12aM6KT.js; 3.375.057 bytes; 765 dòng | export-DfjsImpl.js; 3.369.254 bytes; 757 dòng | Identity khác, phải binding riêng |
| Metrics breakpoint | 762:226096 | Candidate 754:226096; CDP hit thực tế | CONFIG_ONLY cho location đã quan sát |
| Metrics enclosing function | 1.174 bytes; exact text hash `41eea3b9d76012162e09401444e4232e18457777995510d02ad00a03051226c5` | Exact text khác; đúng 1 match normalized token shape, 541 tokens | Tái dùng observation shape có evidence, không proof mọi formula |
| Input breakpoint | 670:42067 | Candidate 662:42067; CDP hit thực tế | CONFIG_ONLY location |
| Input enclosing function | 408 bytes; exact text hash `fdf0f6901a32cdaeeec18f99d56b162ea30f5cee542cd6b5804514acf5bb292f` | Đúng 1 match normalized token shape, 200 tokens | Cần config biến mới |
| Input readback | profile=`N`, options=`T` | profile=`T`, options=`D`; giữ `N` sẽ đọc object React với keys `$$typeof,compare,type` | **Không thể chỉ thay SHA** hoặc chấp nhận mọi object |
| Input epoch | `K.context` object | `K.context` object được quan sát | CONFIG_ONLY reuse expression candidate; lifecycle correlation chưa E2E |
| Resolved metrics/state | `u/f/_`, `l.profile/items/optionEntries/context` | Cùng expression đọc được object/metrics tại location mới | Narrow observation reusable |
| Initial raw metric observations | 168 distinct IDs | 168 IDs, 168 overlaps, 0 raw-value khác trong observation này | Không phải independent expected/attested input hoặc all-build compatibility |
| DOM queried | statsSections=7, `.StatsTest`=1, level input=0, Effects button=0 | Cùng counts | Hai stats selectors REUSABLE cho state này; full editor/navigation selectors UNVERIFIED |

Metrics count 168 là raw observation khi trang recorded khởi tạo, không phải public capability catalog (legacy narrow profile có 50 metrics), không tuyên bố mọi Character Stats/class/equipment đã kiểm thử. Không retag fixture D12 thành Dfjs.

First exploratory probe có bước click New Profile bị modal overlay chặn, timeout ở cả hai snapshots; đã lưu attempt1 private, cleanup PASS. Probe sửa harness thành **read-only initial-page observation** không click, exit 0; D12 6.559s, Dfjs 6.520s. Không gọi interaction path đã PASS; phần đó vẫn UNVERIFIED. Đây không phải product fix hoặc Provider E2E rerun.

## Phân loại integration

| Thành phần | Class | Evidence / còn thiếu |
|---|---|---|
| Verified store, offline mount, BrowserInfrastructure | REUSABLE | Existing verify/mount chạy thật cả hai; egress=0, cleanup |
| Catalog parsing / entity IDs | REUSABLE | Exact catalog byte hash giống; không suy class/item legality ngoài catalog |
| Engine/manifest/provider/codec identity | CONFIG_ONLY | Known exact hashes khác; phải entry Dfjs riêng, không retarget D12 |
| CDP metric/input observation coordinates và locals | CONFIG_ONLY | AST+fresh CDP chứng minh coordinate dịch, N/T→T/D; complete input/phase evidence còn Phase 2 |
| Tách D12 codec guard/provenance khỏi shared codec | IMPLEMENTATION_CHANGE | Constructor/loader/runtimeStateToCanonical/assertions đang hardwired; one-time dependency injection |
| Codec native ↔ canonical cho mọi supported section | UNVERIFIED | Initial profile keys giống không chứng minh round-trip items/paragon/options/class mechanics; cần negative/lossless tests |
| Option flags/params/default/clamp/readback | UNVERIFIED | 1.369 IDs giống không chứng minh eight semantic rules/defaults/bounds giống |
| Metrics extractor core | REUSABLE về interface | Profile-driven capture validation; raw observation cùng shape. Correctness qua actual provider/delta chưa chạy |
| Character Stats formulas / expected values | UNVERIFIED | Không chạy eight APIs, không establish independent expected; initial 168 matches không đủ |
| Universal ComponentFactory DI | REUSABLE | Hiện nhận codec và runtime profile; cần one-time typed loader contract injection |
| Native replay loader envelope | UNVERIFIED | Chưa apply canonical input tới Dfjs qua production adapter; không kết luận CONFIG_ONLY chỉ từ initial page |
| Full selectors, editor/navigation, lifecycle long session | UNVERIFIED | Stats selectors observed; overlay/interaction, eight APIs, preview/commit/reset, phase/cache/session còn Phase 2 |

## Commands/evidence provenance

Các harness Phase 1 nằm private ngoài git; chỉ đọc source/snapshot và thực thi offline observation. Commands đã chạy: `node "$PRIVATE_AUDIT_ROOT/audit-offline.js"` (decrypt+verify+parse/token audit), `node "$PRIVATE_AUDIT_ROOT/probe-offline.js"` (fresh Chromium read-only audit), documentation consistency checker trước commit. Exact private location và evidence manifest hash giao trong handoff; không commit generated logs, raw script assets, DB/profile/key.

Không chạy Real Provider E2E/COMP-04 trong Phase 1; cũng không báo regression suite PASS trên architecture chưa tồn tại. Historical SVER tests/evidence không thay thế COMP gates.

## Acceptance matrix — theo directive mới nhất của Owner

COMP-05 trong body đầu Issue #154 từng dùng cho review evidence; matrix dưới dùng requirement mới nhất: negative fail-closed. Không đổi acceptance của S1–S7 hoặc SNAP-05 riêng.

| ID | Expected / automation sau approval | Actual Phase 1 | Status |
|---|---|---|---|
| COMP-00 | Một authored version file; auto trusted discovery/package; zero edits shared core | Contract/tree/index/S7 policy plan + A/B/C proof blueprint đầy đủ; code chưa viết | PASS thiết kế / runtime NOT_RUN |
| COMP-01 | Audit hardcodes/switch/call graph có exact lines | 22-file slice, adjacent tooling và S7 allowlist, call graph | PASS audit |
| COMP-02 | Owner phê duyệt phương án + one-time plan | PR Draft trình duyệt | PENDING_OWNER |
| COMP-03 | D12 exact guards/behavior giữ nguyên, Dfjs riêng | Known exact identities/changed locals đã phân tích; production chưa refactor | NOT_RUN |
| COMP-04 | Fresh offline Dfjs actual Provider + 8 APIs, independent expected và proven fixture scope | Chỉ Phase 1 observation, không Provider session | NOT_RUN |
| COMP-05 | Unknown/forged/mismatched/revoked binding fail-closed | Test blueprint, existing trust semantics được bảo toàn trong design | NOT_RUN cho refactor |
| COMP-06 | Add synthetic C bằng đúng 1 file, A/B unchanged | Diff/hash/discovery/package proof được đặc tả | NOT_RUN |
| COMP-07 | Performance/session/timeout/cache/generation/cleanup regression | Two read-only probes cleanup PASS; không thay session/performance acceptance | NOT_RUN |

## Detailed Phase 2 tests / independent expected

- **Loader/COMP-00/06:** copied tracked test tree, baseline hash toàn shared core; add duy nhất `versions/synthetic-c.js`, chạy cùng build-index/loader. Assert diff exactly one authored file, deterministic index, C resolves only ISOLATED_TEST approved entry, A/B factories/capabilities/provenance/error behavior unchanged. Generated index/manifest không tính là authored registration. Delete C rebuild → missing implementation fail-closed, không fallback.
- **Trust/discovery negatives/COMP-05:** unknown ID, same ID/different hash, ambiguity, invalid definition contract, unsupported family, tampered index/module, symlink/path escape, module outside app root, untracked/extra .js, user/snapshot JSON execution fields. Assert unknown code không được execute. Valid ciphertext/hash alone không đủ. Test revoked/expired entry, registry rollback, wrong provider/codec/schema/engine/catalog/profile; test key rejected in PRODUCTION.
- **Codec/COMP-03:** D12 canonical/native/export round-trip và exact negative codes trên historical fixtures trước/sau; copy original guard expectations, không thay pins/expected. Dfjs fixture provenance phải đúng r03; preserve raw/unknown semantics, reject unknown fields/unsupported canonical mapping. Losslessness tests cho supported equipment/skills/paragon/effects/options/identity; không yêu cầu live capture.
- **Real Provider/COMP-04:** version-neutral executor discover modules/fixture descriptors, không edit executor mỗi version. Verified approved private offline fixture → independent source native-state/metrics attestation từ snapshot, sau đó same inputs qua actual Registry→Resolver→Factory→Provider→Application. Expected được frozen từ independent source observation, không sinh từ mapper/output đang test. Không lấy D12 raw stats làm oracle Dfjs mặc định. Tám APIs listProviders/createSession/getSession/evaluate/previewChanges/commitChanges/resetSession/closeSession; assert preview không mutate, commit revision/delta đúng, reset baseline đúng, provenance exact binding và finite metrics. Chỉ claim fixture/class/items/metrics đã có evidence; đầy đủ 8 APIs không tương đương mọi build.
- **Option proof:** verify actual registered parameter definitions/defaults/type/bounds, requested-vs-input-vs-resolved option readback, shared options and eight historical rules; không normalize quan sát thành yêu cầu. New bound-control behavior vượt declared hooks → DESIGN_BLOCKED, không nới assertion.
- **Session/COMP-07:** same worker/browser reused, bounded send/evaluate/cleanup, cancellation, page crash, no orphan, generation/cache invalidation và late result wrong-binding rejection. Giữ SNAP-05 failure-path separate; không sửa selection rollback engine trong task này.
- **Performance:** cùng fixture/toolchain/env, report sample count và startup/operation/cleanup P50/P95 trước/sau; không tự đặt SLA hoặc claim PASS chỉ từ một lần chạy. Regressions về queue/session bounds/leaks phải sửa; semantic threshold mới cần Owner quyết định.
- **Packaging:** one-time S7 adapter dùng build-index thật; A/B/C copied exactly tracked hashed modules. Tampered/untracked module/private snapshot/encrypted archive/profile/key bị reject, no network at runtime. Không mở lại installer UAT toàn suite khi không liên quan; packaging execution chờ integration ordering được phép.

7 planned test files: thêm `snapshot-management/tests/compatibility-discovery.test.js`, `compatibility-bindings.test.js`, `providers/maxroll/tests/unit/bound-codec.test.js`, `providers/maxroll/tests/real/dfjs-compatibility.test.js`, S7 `utility/d4planner/tests/test_compatibility_bundle.py`; sửa `snapshot-management/tests/manager.test.js` và S7 `tests/test_public_package.py`. Tests chỉ được triển khai sau approval. Core proof không thay synthetic thành real compatibility.

## Remaining / checkpoint

- COMP-02 Owner design approval bắt buộc trước mọi refactor/product code.
- Full Dfjs behavior/options/independent Provider evidence chưa có; Phase 2 là nhiệm vụ F sau approval, không yêu cầu Owner tự test.
- S7 package policy integration cần ordering hợp lệ với PR mới; không merge/rebase current stack bằng design task.
- Production signing anchor/production approval/distribution permission riêng, không tự cấp; encrypted r03 test-only không phải production license.
- CI_NOT_CHECKED; không capture/release lại, không Windows A. Dừng tại DESIGN_REVIEW_READY.

Documentation validation (Python 3): **4 Markdown files, 40 pinned source references, 4 relative links, 8 acceptance IDs PASS**, 0.084s; exact Dfjs hashes đối chiếu với private audit output. `git diff --check` PASS. Private evidence manifest SHA-256: `3dd1d045dd83397e6a8cf027ee701a68cd185015bc2b3e7fb8a09826a0c6a3c2`; giữ trên Linux F tại `/home/huy/.local/share/streamops/issue154-design/evidence-manifest.json`, không upload raw logs/snapshot. Documentation validation không thay production regression hoặc COMP-04.
