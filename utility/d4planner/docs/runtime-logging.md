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

## Controlled DEBUG reproduction and export

`launcher.json` (existing `d4planner-launcher/v1`) may contain `logging`:

```json
{"schemaVersion":"d4planner-launcher/v1","logging":{"FE":{"websocket":"DEBUG"},"BE":{"capture":"DEBUG","*":"WARN"},"RULEKIT":{"api":"DEBUG"}}}
```

Each component/tag value is its minimum level: DEBUG, INFO, WARN, ERROR; missing/invalid values default to INFO. Normal builds support controlled diagnostics without a global toolchain. Arbitrary messages are intentionally not supported: add a reviewed event/tag and typed safe fields to the three adapters/schema when new instrumentation is needed. Never pass raw exception text, payloads or keys.

From the installation root, `D4Planner.exe --export-logs <runId> <new-absolute-private-directory>` exports three sanitized JSONL files and `manifest.json`. No network/upload, no DB/snapshot/Target. Active-run export is a bounded per-file snapshot, **not** an atomic cross-component transaction; completeness is explicitly BEST_EFFORT_BOUNDED_SNAPSHOT. Last interrupted lines are excluded. Original logs are untouched.

The launcher retains an OS ownership lock until its child lifetime ends. Three active reservations fit under the global budget; if managed/foreign content leaves insufficient space, logging fails open rather than deleting active or foreign data. Temporary compaction files are bounded and counted; cleanup only removes authenticated-by-metadata closed run directories whose three header identities match. The old `private/native-stderr.log` is frozen in place, never appended or deleted. Legacy UAT WebView phase collection is separately bounded to 64 KiB and rejects arbitrary phase/detail strings.

Counters represent diagnostic loss, not delivery guarantees. If storage remains inaccessible until exit, the process cannot persist a final loss counter; export therefore never claims COMPLETE. Runtime functionality and stdout protocols remain independent of logging availability.

### Phục hồi lỗi ghi

Nếu append hoặc atomic replacement thất bại, writer giữ pending dropped count trong RAM. Khi ghi được trở lại, writer phát `LOG_DROPPED` ngay cả khi threshold là ERROR; marker này là diagnostic bắt buộc. `trimmed` chỉ tăng sau khi replacement thành công. Export báo số mất/trim quan sát được trong lịch sử còn giữ, không cam kết lifetime counters sau crash hoặc retention.
