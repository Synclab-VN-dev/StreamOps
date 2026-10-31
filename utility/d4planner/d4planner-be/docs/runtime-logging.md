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

## Review S8-F01…F04

| Finding | Independent assessment | Expected/actual và quyết định |
|---|---|---|
| F01 — generic Browser Infrastructure | AGREE / FIX_REQUIRED | Global symbol mang tên ứng dụng vi phạm INF-11/12 dù optional. Tái sử dụng callback `config.logger` đã có, fail-open; composition của worker inject adapter allowlisted. Không sửa assertion kiến trúc. |
| F02 — export khi app hỏng | AGREE / FIX_REQUIRED | Guard upgrade/payload chạy trước export. Dispatch export trước runtime validation, vẫn kiểm tra application identity, DataRoot, run metadata và destination. Startup bình thường vẫn fail closed. Active metadata hỏng cần explicit DataRoot; identity khác không được bypass. |
| F03 — partial init | AGREE / FIX_REQUIRED | Run directory tạo trước ownership metadata nên lỗi ghi/kill có thể để orphan. Durable `.init` journal trước mkdir, headers fsync rồi rename journal thành metadata đã commit. Recovery chỉ xóa exact header prefixes thuộc journal, sau khi lấy ownership lock. |
| F04 — RESULT outcome | PARTIALLY_AGREE / FIX_REQUIRED | RESULT là completion, không phải success; tuy nhiên event riêng thiếu outcome. Thêm `ok` đã có trong allowlist vào BE/worker completion, không đổi IPC/error behavior. |

`RESULT.ok=true` nghĩa operation đã resolve; `false` nghĩa operation hoàn tất bằng lỗi/timeout/cancellation. REQUEST/ERROR/RESULT dùng cùng correlation hash. Process bị kill trước completion có thể không có RESULT; không suy missing RESULT thành success.

Init journal tối đa 16 KiB và được tính trong global budget. Lỗi trước durable journal chưa tạo run directory. Journal lỗi/không xác minh được hoặc thư mục có foreign contents được giữ và tính quota; không đoán ownership để xóa. Journal hợp lệ của interrupted init được thu hồi ở housekeeping kế tiếp; active lock được giữ nguyên. Crash sau metadata commit để lại closed run hợp lệ, áp dụng retention bình thường. Không tự xóa orphan lịch sử thiếu mọi ownership evidence.

CI Windows quota regression: 65.000 lần ghi đồng bộ trực tiếp vào sink vượt deadline
40 giây của test (và 180 giây trên VM cô lập). Đây không phải SLA IPC/throughput đã
duyệt: production dùng queue/writer thread hữu hạn. Test quota nay seed JSONL hợp
lệ bằng production record encoder tới >99% cap 15 MB không đổi, sau đó ghi 2.500
DEBUG events thật để vượt ngưỡng. Vẫn kiểm tra compaction, zero drops trong workload
này, header/record mới nhất, JSONL và secret canary. Evidence full-volume lịch sử
được giữ nguyên; boundary test không tuyên bố 65.000 writes đạt latency budget.
