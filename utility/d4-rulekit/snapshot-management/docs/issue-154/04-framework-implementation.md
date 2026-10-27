# PR #155 — Framework-only implementation, chờ independent review

Owner approval: [hai PR độc lập](https://github.com/Synclab-VN-dev/StreamOps/pull/155#issuecomment-6446603922). #155 base #146; **không có Dfjs version module**. Issue #156/child PR chỉ bắt đầu sau framework review. Tài liệu 01–03 là audit/design Phase 1 lịch sử, không phải trạng thái approval hiện tại.

## Before → After

| Before | After thực thi |
|---|---|
| D12 identity/provenance/options/profile nằm trong codec, strategies và profile | Một `compatibility/versions/maxroll-20261023.js`; legacy named exports giữ nguyên, delegated shared codec/profile core |
| Strategy map đăng ký từng version | `createStrategies(catalog)` duyệt verified modules/bindings; Factory generic, không sửa Factory để thêm version |
| Literal `rulekit-snapshot-management/1.0.0` có thể dùng lại sau sửa implementation | `rulekit-execution/sha256:<digest>` được tính từ module + shared execution tree, schemas và dependency manifests/locks |
| Generated index chỉ chứng minh consistency của artifact | Signed `entry.ruleKitVersion` phải khớp exact execution identity; sửa bytes + sinh lại index vẫn reject approval cũ |
| Version registration phải sửa source map | Build discovery từ `git ls-files`; synthetic B rồi C mỗi lần thêm đúng một tracked authored file, shared file hashes không đổi |

## Approval binding không đổi Registry schema

Giữ Registry envelope/payload v1 và tám Application APIs. `ruleKitVersion` vốn là string có exact equality; nay identity sinh tự động, không là mutable release label. Digest SHA-256 của canonical sorted `[{path,sha256}]` gồm toàn Rule Kit `src`, schemas, compatibility infrastructure/version modules, package manifests/locks; loại tests/docs và index tự tham chiếu. Index không chứa snapshot bytes, private profile hay signing key.

**Bất kỳ byte thay đổi nào trong indexed execution set đều đòi compatibility approval mới**, kể cả comment-only hoặc thêm một version khác. Đây là conservative fail-closed policy, không tự suy behavioral equivalence. D12 runtime behavior/pins được giữ, **không mặc nhiên giữ hiệu lực approval của old implementation**. Registry cũ có literal version bị `RULEKIT_VERSION_INCOMPATIBLE`; resolver còn kiểm `IMPLEMENTATION_APPROVAL_MISMATCH` để không dùng registry instance có version cũ với strategy mới. `upgradePreflight` hiện có gọi cùng production registry/resolver nên không có exemption cho upgrade. Không rollback Registry revision, DB hoặc tự cấp chữ ký.

Hai lớp khác nhau:

1. Artifact integrity: deterministic index + file hashes, containment, no symlink, verify toàn execution tree trước load version/shared factories. Đây không tự chứng minh app authenticity; app distribution/installation integrity boundary vẫn bắt buộc.
2. Compatibility approval: authenticated signed registry pin exact computed execution identity + existing profile/engine/catalog/binding/evidence. Regenerated self-consistent index không đủ tái dùng approval.

Loader không nhận path từ BE/user/snapshot config. Chỉ bundled trusted application code được execute; không giả Node require là sandbox. Source-build API dùng git tracked files, runtime dùng generated index và không cần git. File ngoài index không được discovery. Duplicate/unknown contract/unsafe path/tamper/symlink fail-closed. Worker đã load code không được relabel cached bytes bằng changed index (`EXECUTION_RESTART_REQUIRED`). Production anchors giữ nguyên, chưa được cấp.

## One-file proof / source ownership

`compatibility-framework.test.js` tạo checkout test riêng từ execution files, thêm synthetic B và C lần lượt. Trước `git add` module không được discover; sau đó index tự nhận, exact signed ISOLATED_TEST binding resolve qua shared Strategy/Factory. Mỗi bước assert đúng một source addition và SHA của mọi file cũ không đổi. Sai profile expression và thiếu engine/catalog bị reject. Synthetic evidence không chứng minh Dfjs compatibility.

Factory family selection theo `ui-cdp/v1` hoặc `native-state/v1` là runtime-family dispatch, không snapshot ID/engine switch. D12 facades phục vụ existing imports; future versions không đi qua facade. Shared codec giữ một implementation, bind immutable definition trong closure. Native loader helper generic giữ alias cũ. Không thêm Dfjs vào #155, không đổi FE/BE, snapshot baseline hay production trust.

Generated index là build artifact bắt buộc và được version control để checkout dùng được ngay; không phải handwritten registration. Thêm version N+1: một authored file rồi chạy build-index để regenerate artifact. Không sửa Factory/Resolver/codec/profile source. Các artifacts approval/evidence riêng vẫn cần chữ ký/kiểm chứng đúng policy.

## Commands và evidence

Từ root repo:

```bash
node utility/d4-rulekit/snapshot-management/compatibility/build-index.js
node --test utility/d4-rulekit/snapshot-management/tests/*.test.js
npm run test:unit --prefix utility/d4-rulekit/providers/maxroll
npm run test:contract --prefix utility/d4-rulekit/providers/maxroll
npm run typecheck --prefix utility/d4-rulekit/providers/maxroll
# Chromium/fixture env phải trỏ private offline resources đã được phép.
node --test --test-concurrency=1 utility/d4-rulekit/providers/maxroll/tests/adapter-real/universal-provider.test.js utility/d4-rulekit/snapshot-management/tests/real/d12-framework.test.js
# dùng Python venv đã provision, với PYTHONPATH=utility/d4planner/src:
python -m pytest -q utility/d4planner/tests/test_rulekit_worker.py utility/d4planner/tests/test_snapshot_worker.py
git diff --check
```

Test-only harness dùng ephemeral Ed25519 key trong memory và `ISOLATED_TEST`, không production signing. Actual managed Node worker chạy D12 provider qua trusted generic resolution, real Chromium offline, independent expected 50 metrics, input options EXACT và shutdown asserts stopped/zero contexts. Eight-API D12 regression riêng giữ existing independent Midgame/Endgame oracle, preview/commit/reset và negative readback tests. Không gọi synthetic browser fixtures là Maxroll E2E.

Fail-first framework test trước implementation: module missing → FAIL. Refactor debugging phát hiện variable shadowing trong option definition map và missing reference argument khi extract profile defaults; đã sửa implementation. Test harness mới ban đầu dùng sai metric ID field và worker relative path; đã sửa theo existing public schema/path, giữ nguyên independent expected values. Final counts/durations/exact HEAD giao trong PR handoff; private logs nằm ngoài git.

## Acceptance / remaining checkpoints

| Gate | Actual | Status |
|---|---|---|
| COMP-00 | Automatic tracked discovery/index + generic factory, one-file proof | LOCAL_PASS ở Rule Kit; S7 packaging riêng |
| COMP-01 | Audit vẫn giữ exact parent references | PASS |
| COMP-02 | Owner duyệt framework-only implementation | APPROVED; independent review còn chờ |
| COMP-03 | D12 migrated/legacy regression, không có Dfjs source | D12 LOCAL_PASS; Dfjs thuộc #156 |
| COMP-04 | Dfjs real Provider chưa chạy/không thuộc #155 | NOT_RUN / #156 |
| COMP-05 | Modified module/core + regenerated index + stale signed entry rejected; negatives | LOCAL_PASS; production trust không kích hoạt |
| COMP-06 | Synthetic third C thêm một authored source, shared hashes giữ nguyên | LOCAL_PASS / SYNTHETIC_ONLY |
| COMP-07 | D12 eight APIs, real worker, session/cleanup và existing targeted regression | LOCAL_PASS trong fixture coverage đã chạy |
| S7 installation/package | Không sửa #150 hoặc copy source ngược | OWNER_INTEGRATION_CHECKPOINT |

S7 adapter phải bundle **toàn execution inventory** và generated index, verify public-content policy/negative inspection; không chỉ copy version file. `build-index.js` là interface cho owning #150, không có implementation packaging ở #155. Không tuyên bố Setup đã hỗ trợ one-file modules. Không tự rebase #147→#150.

Giữ #155 Draft: `PR155_REFACTOR_READY_FOR_REVIEW / CI_NOT_CHECKED`. Không mở child #156 trước reviewer xác nhận. SNAP-05 riêng, không sửa/fix claim. No capture/release/Windows A/production activation.
