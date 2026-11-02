> CI #166: workflow hiện tại là `.github/workflows/main.yml`, product contract ở `utility/d4planner/ci.release.py`. Manual build dùng operation=build, product=d4planner-release, version=<version>; publish là operation riêng. Core build/verify dùng chung với VM; policy bên dưới phản ánh quyết định Owner mới nhất.

# Release CI D4Planner Application

Một workflow `CI`: `.github/workflows/main.yml`; build/release implementation thuộc product contract.
Test/UAT installer dùng manual `operation=build`, `product=d4planner-release`,
`version=X.Y.Z`: build → verify → Actions artifact. Không tạo GitHub Release.
Production dùng manual `operation=publish` trên trusted master. Không auto publish
khi push tag; version nhập tay không bị ghi đè theo ref.

Build từ F qua Windows VM và lấy Setup/log về F: [hướng dẫn VM build](../../script/build/README.md).
Wrapper tự khởi động VM builder đã enrollment và cài toolchain thiếu; không dispatch Actions hoặc publish.

## Một nguồn Product Version

`package-plan.json.version` là nguồn chuẩn Application Product Version. Release CI
reject input `version` khác plan trước build. Manifest, Setup filename,
`VIProductVersion`/DisplayVersion và metadata đều dùng giá trị này. Version các
crate/npm/Python component là version nội bộ, không phải Application version.

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
Snapshot vẫn là `.zip.age` riêng, không chứa trong Setup. Metadata artifact không
còn UAT revision hoặc release tag giả định. `UAT.md` là hướng dẫn test artifact,
không phải authorization publish hay bằng chứng Owner MAN.

### Policy build-only / publish

- Build-only không query GitHub Release, không đọc production credential và không
  publish. Cùng version có thể build lại. Version phải đúng package plan; mismatch
  bị báo lỗi, không bị silently override.
- Build phase của publish cũng không nhận production credential. Sau build/verify,
  publish job xác minh source/version/checksum, rồi kiểm tra Release `vX.Y.Z`.
  Đã tồn tại thì dừng; chỉ HTTP 404 rõ ràng được coi là chưa tồn tại. Auth, network,
  rate limit, timeout hoặc malformed response đều fail closed.
- Tag có sẵn chỉ được tái sử dụng nếu resolve đúng source HEAD. Không move tag,
  overwrite Release hoặc thêm asset vào Release đã tồn tại.
- Theo threat model Owner chốt ngày 2026-11-02, write collaborators (gồm bot) là
  trusted; giữ same-repository feature branches. Không yêu cầu chống collaborator
  malicious/compromised sửa workflow. Chỉ job manual publish trên master nhận
  GITHUB_TOKEN contents:write; PR/test/build giữ read. Không cần PAT/Environment
  mới hoặc thêm Review deployments. Thiếu token vẫn BLOCKED. Xem
  [CI contract](../../../../../.github/workflows/CI-CONTRACT.md).

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
