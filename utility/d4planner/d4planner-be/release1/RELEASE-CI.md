# Release CI D4Planner Application

Một workflow `D4Planner Release`: `.github/workflows/d4planner-release.yml`.
UAT dùng push tag trên exact feature SHA, không cần merge master. Dispatch vẫn
có `version` X.Y.Z, `build_only=true` mặc định; dispatch chỉ khả dụng khi workflow
có trên default branch. CI run không phải Product Version.

## Một nguồn Product Version

`package-plan.json.version` là nguồn chuẩn Application Product Version. Release CI
reject input `version` khác plan trước build. Manifest, Setup filename,
`VIProductVersion`/DisplayVersion và metadata đều dùng giá trị này. Version các
crate/npm/Python component là version nội bộ, không phải Application version.

`uat-encryption-policy.json.uatRevision` là số candidate UAT dương. Tag là
`d4planner-uat/vX.Y.Z-rN`; ví dụ Product1.2.8, UAT1.2.8-r1. Một rerun cùng SHA không
tăng Product Version. Nếu candidate có nội dung khác sau lỗi harness/build, dùng
revision UAT mới, tag/asset cũ bất biến. Product Version tăng khi thay đổi sản phẩm
được bàn giao (1.2.8 sửa compression và console launch). CI run ID chỉ lưu metadata.
Windows upgrade/rollback tiếp tục so sánh version X.Y.Z và payload hash; same-version
reinstall giữ behavior đã kiểm thử, không bỏ downgrade/ownership/schema guards.

## Build và publication

Checkout exact SHA với LF. Runtime/tree hashes và Cargo/npm lockfiles được pin:
Python3.12.10, Node22.22.1, Rust1.90.0, NSIS3.09, Chrome for Testing156.0.8078.4,
Playwright Core1.64.1. Không tải dependency lúc install/launch.

Build source FE (generate icon, static CRT), root launcher, Backend wheel, Rule Kit;
assemble allowlisted stage → ZIP DEFLATE level6 cho **từng entry** → NSIS Setup.
NSIS giữ `SetCompress off` quanh payload ZIP để tránh nén lại dữ liệu đã nén.
Bootstrap và maintenance Python giữ độc lập với payload để fresh install/uninstall
và recovery không cần Python hệ thống. Không prune Chrome locale/codec/module.

Health probe dùng payload extract từ verified ZIP, có release-manifest đầy đủ:
FE → Backend → Node/Chrome → authenticated WS → restart/stop/owned cleanup.
No-snapshot calculation phải UNAVAILABLE; health không thay native UI acceptance.

Application UAT bàn giao trực tiếp `D4Planner-Setup-X.Y.Z.exe`, SHA256SUMS,
release-metadata.json và UAT.md. Không cần age identity/decrypt để cài Application.
Snapshot vẫn là `.zip.age` riêng. File policy giữ tên cũ `uat-encryption-policy.json`
để không tạo hai nguồn chuẩn, nhưng schema v2 mô tả distribution format riêng cho
Application và Snapshot; policy trong source **không phải** license approval.

### Policy build-only / publish (Owner cập nhật 2026-11-01)

- `build_only=true`: build và upload artifact đã verify. Không query GitHub Release,
  không đọc approval secret, không chạy publish job. Build lại cùng version/HEAD
  hoặc HEAD mới không cần cập nhật secret.
- `build_only=false`: kiểm tra Release `vX.Y.Z` trước build và kiểm tra lại ngay
  trước publish. Release đã tồn tại thì dừng, không overwrite/upload thêm assets.
  Chỉ HTTP 404 rõ ràng được coi là chưa tồn tại; lỗi auth, rate limit, network,
  timeout hoặc response không hợp lệ đều dừng. Không tự tăng version.
- UAT tag giữ namespace `d4planner-uat/vX.Y.Z-rN`, dùng cùng kiểm tra Release tồn tại.
  Luồng UAT vẫn kiểm tra tag/source context và metadata định dạng của artifact.
- Tag có sẵn nhưng chưa có Release được dùng lại nếu resolve đúng commit build,
  kể cả annotated tag. Tag trỏ commit khác bị chặn để không di chuyển tag hoặc
  gắn binary mới vào source cũ. Tag chưa có được tạo bằng API không force.
- Workflow không còn sử dụng `D4PLANNER_DISTRIBUTION_APPROVAL_JSON`,
  `D4PLANNER_RELEASE_GATES_JSON`, `D4PLANNER_UAT_RELEASE_APPROVAL_JSON`, hoặc
  environment `d4planner-release`. Không cần sửa/xóa secret hay repository settings.

Build vẫn giữ content allowlist/negative inspection, runtime pins, full manifest,
ZIP hashes và runtime health. Upload giữ exact binary/hash, kiểm tra asset allowlist,
checksum, source/version; publish tải đúng artifact ID, không rebuild/overwrite.
Binding source/version/checksum **giữa artifact và lượt build** vẫn bắt buộc;
chỉ bỏ binding với approval secret. Staging runner owner-only, cleanup always.
Không chứa private snapshot, credentials hay Gateway server trong Setup.

Thay đổi policy tự động hóa không phải bằng chứng Owner MAN, Visual hoặc production
acceptance đã PASS. Không thay Snapshot compatibility/trust policy.

## Snapshot/trust hiện tại

Application Setup không có Maxroll Snapshot/profile private, kể cả encrypted.
Snapshot Release độc lập:
https://github.com/Synclab-VN-dev/StreamOps/releases/tag/d4planner-snapshots/2026.10.30-r2

Production verification public key đã pin trong Rule Kit. Signed Registry revision2
bind exact execution identity; test keys không được production trust. Snapshot bundle
mã hóa được import qua root launcher's Snapshot Management forwarding → Rule Kit,
không qua FE/BE resolver. D12/Dfjs chỉ được chứng minh trong approved Rogue fixtures.
Registry expiry/revocation/anti-rollback vẫn bắt buộc. Không có snapshot: Equipment/
HUD hoạt động, calculation UNAVAILABLE. Upgrade/rollback hỏi Rule Kit preflight trước
mutation và giữ external store, DB, Targets, Settings; không restore DB cũ.

## Evidence baseline

Application1.2.7 CI run41008842415 SUCCESS; clean-machine offline VM và active signed
snapshot T18 PASS. #158 chứa evidence/hashes và các candidate thay thế. Historical
PASS không tự trở thành PASS cho artifact mới; regression chọn theo ảnh hưởng.


## S7-REL-01 — đánh giá lịch sử (policy approval đã được thay thế ở trên)

PARTIALLY_AGREE / FIX_REQUIRED. Encrypted Application có căn cứ ở policy phân phối
cũ; không phải tự mở rộng Snapshot policy. Contract mới yêu cầu Setup cài trực tiếp,
nhưng không tự xác minh quyền redistribution plaintext của bundled runtimes.
Phương án tối thiểu là đổi output/metadata/workflow đồng bộ và tách exact-source
redistribution approval khỏi exact-artifact publication approval. Không thay installer,
FE/BE/Rule Kit hoặc snapshot path. Thiếu approval thì source sẵn sàng review nhưng
public artifact/handoff vẫn BLOCKED; không dùng PASS ciphertext CI cũ thay gate mới.
