# DFJS-04 — independent engineering assessment và targeted resolution

Nhận định trước khi sửa: [PR comment](https://github.com/Synclab-VN-dev/StreamOps/pull/157#issuecomment-6457698564), source reviewed `1d23a868b1c74d9a90873e74f0d197daefed558d`.

**Reviewer claim:** E2E chưa so projection source với replay. **Dev F: đồng ý về evidence gap, không kết luận production bug. Decision: FIX_REQUIRED (tests/evidence only).**

Existing `verifyRuntimeItemProjection` kiểm full observed input bằng expected; active map là exact subset, omission trong declared slots. Runtime attestation so active items ở metrics frame với input frame projection cùng epoch, giữ exact profile/options. Điều này chứng minh replay self-consistency. Source oracle đã lưu riêng projection nhưng E2E cũ chỉ đọc metrics/options; source→replay active subset chưa được so trực tiếp.

50 raw metrics exact chứng minh outputs đó, không chứng minh mapping item→metrics injective. Ví dụ logic: một Charm bị loại trong nhóm được phép nhưng chỉ ảnh hưởng metric ngoài 50 hoặc effect không active trong options hiện tại; input vẫn nguyên, input/metric frames cùng bỏ item, sampled metrics vẫn bằng. Đây không phải khẳng định bug này đang xảy ra ở hai fixtures. So projection với source thêm independent cross-execution constraint, không lặp lại self-consistency.

## Fix tối thiểu

Chỉ test files ở #157, không thay production core, module, API, Registry hoặc parent #155:

- `tests/real/projection-oracle.js`: yêu cầu frozen source evidence khi profile có projection; so semantic `inputItemsSha256`, `calculationItemsSha256`, `calculationItemCount`, `omittedSlots`. Slot order được canonicalize, duplicate slot bị reject. Không so timestamps/CDP IDs/object order. Missing evidence fail, không fallback từ replay.
- `tests/real/d12-harness.js`: expose Boolean policy từ trusted profile cho test; không route theo snapshot ID.
- `tests/real/d12-framework.test.js`: assertions tại direct baseline, managed baseline, sau preview, commit B, reset A. Existing all8/revisions/metric/options/cleanup assertions giữ nguyên. D12 không policy kiểm cả source/replay không có projection.
- `tests/projection-oracle.test.js`: giữ metrics không đổi nhưng mutate từng projection field phải reject; thiếu source/replay reject; legacy absence pass. Synthetic comparator tests không phải real compatibility proof.

Expected dùng nguyên source-only oracle trước Provider run, không regenerate/capture mới: A full18→calculation15/omit24,25,26; B18→18/omit none. Final run log xuất hashes/count/slots expected+actual theo state, không xuất raw private items. Private oracle hashes phải khớp manifest evidence vòng trước.

## Validation và limits

Targeted commands: `node --test utility/d4-rulekit/snapshot-management/tests/projection-oracle.test.js`; `node --test utility/d4-rulekit/snapshot-management/tests/real/dfjs-framework.test.js`; `node --test utility/d4-rulekit/snapshot-management/tests/real/d12-framework.test.js`; `git diff --check`. Real suites dùng pinned local Chromium, existing private offline snapshot/fixture roots, isolated signed Registry. Exact HEAD/results/duration và private evidence manifest đăng ở PR handoff.

Hai execution độc lập nhưng source/replay dùng chung observation implementation: common-mode observer defect vẫn là giới hạn. Không claim độc lập tái triển khai Maxroll formula; không mở rộng proof ngoài hai recorded Rogue variants, không production trust approval. CI_NOT_CHECKED; cả hai PR Draft; SNAP-05/S7 packaging ngoài scope.

## Real-run finding: raw equality khác semantic equality

First targeted run (`f1b36df`) FAIL ở committed B: source hash `76c5b373…`, replay `535a4643…`, nhưng count18/omitted=[] đúng. Independent field diff cho thấy duy nhất `items.20.aspects: []` ở source bị codec bỏ. A không có delta. Ngoài ra direct Provider test đọc sai provenance envelope; sửa test để truyền provider provenance đúng cấu trúc, không fallback.

**Decision cập nhật: NEEDS_DIFFERENT_SOLUTION cho raw-hash equality tuyệt đối.** Không đổi production codec/schema chỉ để giữ optional empty representation; cũng không thay frozen oracle. Existing codec decode `item.aspects ?? []`, encode chỉ khi length>0. Pinned engine aspect iterator tại byte offset1015255/1015273 guarded yield*, absent và [] đều không yield; quality check1018344 xét length. Đây là evidence cho empty-aspect calculation semantics, không claim mọi UI behavior.

Comparator cuối xác minh raw source input/active hashes và count từ frozen `runtimeState.items` + source omission trước. Derived expected chỉ bỏ `aspects: []` ở item level theo existing canonical contract, không gọi production Codec/Provider, không lựa hash dựa vào actual. Mọi nonempty aspect, item/slot/count/omission/value giữ nguyên. Replay so exact với derived source semantic hashes. Logs giữ original source hashes, normalization paths, derived expected và actual; **B không đạt raw hash equality và không được báo là đạt**. A baseline/reset không cần normalization. Thêm negative kiểm source tamper và nonempty aspect loss; mutation loại assertion phải bị unit tests bắt.

Quan điểm/evidence đã đăng trước thay đổi giải pháp: [assessment bổ sung](https://github.com/Synclab-VN-dev/StreamOps/pull/157#issuecomment-6457760055). DFJS-04 đề xuất PASS theo semantic input/subset equivalence trong hai variants, không phải raw JSON identity. Reviewer quyết định chốt finding; không tự resolve review.
