# Issue #154 — Snapshot Compatibility Framework / Dfjs design

**DESIGN_REVIEW_READY — Phase 1, chỉ tài liệu; COMP-02 PENDING_OWNER.**

Parent PR #146 / `feature/140-d4planner-rulekit-worker`, exact audited HEAD `fd87a98325b36f3fd8931af217155643484a5c87`. Requirement: [Issue #154](https://github.com/Synclab-VN-dev/StreamOps/issues/154), [one-file addendum](https://github.com/Synclab-VN-dev/StreamOps/issues/154#issuecomment-6444672089). PR mới base trực tiếp parent, không sửa #146, không mang sibling commits vào branch.

Mục tiêu: sau one-time refactor, hỗ trợ snapshot N+1 thuộc runtime family/extension points đã có bằng **một compatibility version file**, shared Registry/Resolver/Codec/Profile/BE/FE không phải sửa theo version. Guard mismatch hiện tại không phải evidence formula Dfjs sai.

| Before | After đề xuất (chưa implement) |
|---|---|
| D12 bindings phân tán trong codec/profile/strategy/option tables | Một D12 definition; một Dfjs definition; shared bound core + legacy facades |
| Thêm runtime cần tối thiểu 5 definition files + attestation helper | N+1: **1 authored version file**, zero shared/core/manual registration edits khi family đủ |
| Strategy catalog thủ công | Trusted bundled automatic discovery + generated hash index, exact resolver |
| Package source allowlist liệt kê từng file | One-time S7 adapter nhận exact generated module inventory; không copy user/snapshot code |
| Có integrity + offline replay, nhưng r03 guard mismatch | Compatibility proof riêng qua real Provider/eight APIs sau design approval |

Đề xuất **A có điều kiện**, không clone codec: parameterize exact binding/native contract/option authority/readback; D12 facade bảo toàn guards. B/adaptation chỉ mở khi Phase 2 chứng minh behavior vượt extension points và Owner duyệt mở rộng. Không biến same catalog/option IDs/initial metrics thành formula compatibility PASS.

Tài liệu review:

1. [Audit hiện tại, exact source lines, hardcode inventory, current call graph](01-current-audit.md).
2. [Thiết kế, diagram/tree, một-file contract, trusted discovery, A/B tradeoffs, Before→After file budget](02-proposed-design.md).
3. [Private offline evidence đã kiểm tra, REUSABLE/CONFIG_ONLY/IMPLEMENTATION_CHANGE/UNVERIFIED, COMP-00…07 và test plan](03-evidence-and-acceptance.md).

**Thêm snapshot N+1 yêu cầu sửa 1 authored file: `compatibility/versions/<version>.js`; refactor lần đầu dự kiến 25 production/build/policy files (17 sửa + 8 thêm), cộng 7 tests = 32 files.** 22 production/build files thuộc Rule Kit/worker; ba S7 files thuộc #150 và cần integration ordering riêng. Generated registry/profile/package/index/evidence artifacts vẫn tồn tại theo trust policy, không phải manual source registration. Behavior mới chưa biểu diễn được → DESIGN_BLOCKED cho version đó, không hidden switch.

Evidence Phase 1: r03 giải mã private và verify tất cả blobs; catalog SHA/tập 1.369 option IDs trùng D12; AST+CDP cho thấy metrics breakpoint 762→754, input breakpoint 670→662 và locals N/T→T/D. Hai fresh Chromium offline observation đọc 168 raw metric IDs mỗi bên (initial values trùng), egress=0, cleanup PASS. Đây **không** là Provider E2E hoặc input/option/formula compatibility; full navigation/selector/interactions, native round-trip và eight APIs chưa chạy.

Owner cần duyệt phương án/refactor plan và packaging dependency tại [checkpoint cụ thể](02-proposed-design.md#owner-decisions-cần-chốt-tại-checkpoint-này). **Dừng Phase 1 ở đây; không triển khai production code trước approval.** Không đổi eight APIs/canonical schema/trust policy, không merge/release/capture/CI/A; SNAP-05 finding riêng. `CI_NOT_CHECKED`.
