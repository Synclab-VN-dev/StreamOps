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

Trước mọi upload (cả build_only), `prepare-upload` và `validate-upload` kiểm tra
`D4PLANNER_DISTRIBUTION_APPROVAL_JSON` qua environment. Approval phải có
`approvedBy: TrdHuy`, `approvalRef`, exact `sourceHead`, `version`,
`publicDistributionApproved: true`, `licensesVerified: true`,
`artifactClass: D4PLANNER_APPLICATION_NO_SNAPSHOT`,
`distributionFormat: PLAINTEXT_EXE`, và `runtimeLockSha256` đúng file
`release-runtime-lock.json`. Phạm vi phải bao phủ Application và toàn bộ bundled
Python/Node/Chrome/dependencies; quyền tải upstream hay approval encrypted-only
không thay thế quyền phân phối plaintext. Không đưa tài liệu/thỏa thuận riêng vào
source/logs. Approval là attestation được Owner cung cấp qua kênh quản lý hiện có,
không phải bằng chứng F tự kiểm chứng hợp đồng; F không tự điền true.

Build private giữ content allowlist/negative inspection, runtime pins, full manifest,
ZIP hashes và runtime health. Upload giữ exact binary/hash, kiểm tra asset allowlist,
checksum, source/version; publish tải đúng artifact ID, không rebuild/overwrite.
Staging plaintext chỉ nằm runner owner-only, cleanup always; không upload trước gate.
Thiếu approval: fail-closed, không có public artifact dù build thành công.

UAT publish còn cần `D4PLANNER_UAT_RELEASE_APPROVAL_JSON`: `approvedBy`,
`approvalRef`, `publicationApproved: true`, exact `sourceHead`, `version`, `sha256`,
`releaseTag`. Đây là approval độc lập với redistribution. Workflow tag chỉ hợp lệ
trên exact SHA; chưa tạo tag/release nếu chưa đủ approval. Candidate dự kiến
1.2.8-r2 giữ Product1.2.8 vì chỉ đổi delivery contract, không đổi app binary logic.
Giữ 1.2.8-r1/asset cũ để audit; chưa công bố r2. Historical encrypted verifier chỉ
phục vụ audit, không được workflow mới gọi để cấp quyền upload.

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


## S7-REL-01 — đánh giá độc lập

PARTIALLY_AGREE / FIX_REQUIRED. Encrypted Application có căn cứ ở policy phân phối
cũ; không phải tự mở rộng Snapshot policy. Contract mới yêu cầu Setup cài trực tiếp,
nhưng không tự xác minh quyền redistribution plaintext của bundled runtimes.
Phương án tối thiểu là đổi output/metadata/workflow đồng bộ và tách exact-source
redistribution approval khỏi exact-artifact publication approval. Không thay installer,
FE/BE/Rule Kit hoặc snapshot path. Thiếu approval thì source sẵn sàng review nhưng
public artifact/handoff vẫn BLOCKED; không dùng PASS ciphertext CI cũ thay gate mới.
