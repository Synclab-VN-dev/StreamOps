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

Public UAT chỉ có `.exe.age`, checksum, safe metadata và UAT instructions. Toàn
Setup mã hóa bằng age1.3.2 được pin trước upload. Plaintext runtime/Setup staging
ACL owner-only và cleanup always; không cache/upload plaintext, snapshot hay keys.
Policy UAT scoped Owner attestation độc lập với stable `licensesVerified`; không
khẳng định đã độc lập kiểm tra thỏa thuận phân phối. Publish tải đúng artifact ID,
verify source/tag/version/revision/hash, không rebuild/overwrite. F tải lại artifact,
giải mã và native-test trước handoff; private identity không nằm trên Actions.

Stable publish vẫn cần protected `d4planner-release` environment, Owner approval
và exact-artifact gates PKG/HUD/SNAP. UAT không phê duyệt stable/merge/Owner MAN.
T12/VISUAL_GOLDEN chỉ R1 ghi OWNER_WAIVED theo `ISSUE158_R1_VISUAL_WAIVER_20261030`,
không ghi PASS và không áp dụng cho project/release khác. T20–T23 chờ Owner.

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
