# Release CI D4Planner

Chỉ một workflow `.github/workflows/d4planner-release.yml`, tên **D4Planner Release**,
trigger `workflow_dispatch`, inputs `version` X.Y.Z và `build_only` boolean mặc định
true. Checkout đúng `github.sha`, action SHAs cố định; Python 3.12.10, Node 22.22.1,
Rust 1.90.0, NSIS 3.09, Chromium 156.0.8078.4, Playwright Core 1.64.1.
Npm/Cargo dùng lockfiles; dependencies BE dùng `requirements-release.txt`.
Không chạy workflow trong đợt sửa này. File ở feature branch chưa đồng nghĩa có
thể dispatch: GitHub yêu cầu workflow hiện diện trên default branch.

## Input private, không tải latest

Owner cấu hình secrets (F không thay repository settings):

- `D4PLANNER_RELEASE_INPUTS_URL`: HTTPS URL private/signed tới ZIP inputs đã review.
- `D4PLANNER_RELEASE_INPUTS_SHA256`: SHA-256 chính xác của ZIP trên.
- `D4PLANNER_DISTRIBUTION_APPROVAL_JSON`: attestation theo exact source/version,
  snapshot pin và quyền phân phối công khai. Repository hiện public, Setup chứa
  snapshot private; thiếu quyền thì workflow dừng **trước build/upload**. Không
  ngầm xem quyền build như quyền upload công khai.

ZIP inputs có thư mục `python`, `node`, `chromium`, `snapshots`, `config` và `nsis`.
`inputs-manifest.json` chứa `schemaVersion: d4planner-private-build-inputs/v1`,
`versions` giống `release-runtime-lock.json`, và `files` với path/sha256 cho **mọi**
file khác trong ZIP. Runtime binary và snapshot manifest phải khớp hash đã pin
trong source; mọi file còn lại khớp trusted archive+manifest, không symlink hay
path escape. Không chứa credentials/DB. NSIS Windows portable lấy bản 3.09 tại
https://sourceforge.net/projects/nsis/files/NSIS%203/3.09/ (ZIP SHA-256
`f5dc52eef1f3884230520199bac6f36b82d643d86b003ce51bd24b05c6ba7c91`).

Attestation distribution (các giá trị binding do Owner cung cấp cho source cụ thể):
`sourceHead`, `version`, `snapshotManifestSha256`, `approvedBy: TrdHuy`,
`approvalRef`, `publicDistributionApproved: true`, `licensesVerified: true`.
Không đặt secret hoặc URL private vào source/report công khai.

## Build-only

`release_ci.py` verify inputs → build FE/root bằng Cargo locked → build BE wheel
và site-packages pinned → install Rule Kit JS dependencies qua npm lock → gọi
`build_release1_stage.py`, `release1_delivery.py`, `build_windows_installer.py`.
Có unit/contract/package tests, static manifest/SHA validation và actual native
FE self-test khởi động/restart/stop BE/Rule Kit/Chromium trong owned Job.
Probe không thay native visual acceptance.

Artifact chỉ gồm **Setup EXE + release-metadata.json + SHA256SUMS**; không upload
ZIP input, raw snapshot/DB/log/credentials. Setup tự chứa private resources, nên
cả upload Setup cũng cần distribution approval. Không tạo GitHub Release khi
`build_only=true`.

## Publish opt-in

`build_only=false` vẫn chạy toàn bộ build trên. Trước đó verify environment
`d4planner-release` đã tồn tại, required reviewer duy nhất **TrdHuy**, prevent
self-review bật. Thiếu gate/API quyền đọc thì dừng; không tạo environment tự động.
Job publish chờ protected environment approval; F không tự cấu hình/approve.

Environment secret `D4PLANNER_RELEASE_GATES_JSON` phải bind `sourceHead`, `version`,
`sha256` của đúng Setup, `approvedBy: TrdHuy`, `approvalRef`; `gates` yêu cầu
PKG-01…08, HUD-03 và VISUAL_GOLDEN đều PASS. Hiện các MAN/Golden chưa PASS nên chưa
release-ready. Offline negative vẫn DEFERRED_OWNER trong acceptance hiện tại.

Download đúng immutable artifact ID từ job build, đối chiếu Setup SHA với output
job và metadata, verify lại distribution/Owner/gates; từ chối release/tag đã tồn
tại hoặc không xác minh được. Create tag bằng API không force; publish chính Setup
đã build/test, không rebuild. Nếu publish lỗi sau tạo tag, giữ fail và để Owner
xử lý checkpoint tag; không ghi đè/xóa tag tự động.

Tài liệu GitHub:
[Environment protection](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[workflow_dispatch](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).
