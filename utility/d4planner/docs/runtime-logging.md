# S8 — Runtime logging (implementation working contract)

## Independent Engineering Assessment (before implementation)

| Nhận định | Đánh giá / quyết định | Evidence, ảnh hưởng và lựa chọn |
|---|---|---|
| Cần một framework chung | PARTIALLY_AGREE / NEEDS_DIFFERENT_SOLUTION | BE stdout là managed protocol; Node stdout là IPC. Chung schema/policy, adapters native riêng, không thêm service/business dependency. |
| Ba file và single writer | AGREE / FIX_REQUIRED | Launcher append native-stderr; Tauri eprintln; Python drain stderr bỏ raw. Root ghi FE trước spawn/sau confirmed exit; Tauri ghi giữa hai mốc. BE/worker một writer queue mỗi process, restart sau owned exit. |
| Compact Windows | AGREE / FIX_REQUIRED | Không giữ target file handle giữa writes. Đóng/fsync temporary rồi replace; failed replace giữ original, drop bounded. Temporary nằm control area, không rollover lâu dài. |
| Hard/global quota | AGREE / FIX_REQUIRED | Reserve worst-case live file + compact temporary cho active run dưới global lock; không chỉ cộng file size tại startup. Không xóa active runs để lấy quota; fail-open logging unavailable nếu thiếu budget. |
| Early errors | AGREE / FIX_REQUIRED | Bootstrap log trước READY; sanitize exception thành event/code, không raw stderr. Frozen native-stderr lịch sử không bị xóa hay append. |
| IPC/latency | AGREE / FIX_REQUIRED | Bounded nonblocking producer queue, consumer riêng; Node writer thread. Drop counters khi queue/full/I/O error; stdout không chứa log. Đo overhead, không đặt SLA mới. |
| Execution identity | AGREE / FIX_REQUIRED | Rule Kit source graph hashed; logging integration có thể đổi execution identity. Recompute index, ký registry sandbox đúng identity nếu cần; không sửa public release/bypass pins. |

Limits: FE5,000,000 / BE10,000,000 / RULEKIT15,000,000 bytes. Global200,000,000; retention14days closed runs. JSONL schema `d4planner-runtime-log/v1`; controlled tags/events and numeric/bool fields, no raw exception/payload/path. DEBUG opt-in by component/tag; INFO default. Logging/export errors never imply application failure.

S8 không có Report Issue UI/upload. CI_NOT_CHECKED cho tới khi có quyền riêng.
