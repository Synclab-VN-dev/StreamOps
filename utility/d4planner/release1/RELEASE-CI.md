# Release CI D4Planner Application

Chỉ một workflow `.github/workflows/d4planner-release.yml`, tên **D4Planner Release**,
trigger `workflow_dispatch`, inputs `version` X.Y.Z và `build_only` mặc định true.
Checkout đúng `github.sha`; actions và runtime được pin. Workflow chưa được chạy
trong đợt này. File trên feature branch chưa đồng nghĩa dispatch được: cần có
workflow trên default branch. Không tự merge hoặc kích hoạt Actions.

## Application và snapshot là hai kênh riêng

Setup chứa HUD, Backend, Rule Kit, Python, Node và Chromium; **không chứa Maxroll
Snapshot hoặc profile private**, kể cả dạng encrypted. Snapshot store nằm ở
DataRoot/rulekit, ngoài application root, chỉ Rule Kit quản lý. Không có snapshot:
FE/BE/Equipment hoạt động, calculation UNAVAILABLE. Production trust activation
BLOCKED tới khi Owner chỉ định public key/key ID chính thức. Test key không được
production tin cậy. Quyền phân phối snapshot công khai chưa được cấp.

## Build input công khai đã review

Owner cấu hình các secrets sau khi review; F không thay repository settings:

- `D4PLANNER_PUBLIC_RUNTIME_INPUTS_URL`: HTTPS URL tới archive chỉ có Python, Node,
  Chromium và NSIS. Không đưa snapshot/profile vào archive rồi lọc bỏ sau download.
- `D4PLANNER_PUBLIC_RUNTIME_INPUTS_SHA256`: phải khớp digest đã pin trong
  `release-runtime-lock.json`; archive private cũ bị từ chối trước download.
- `D4PLANNER_DISTRIBUTION_APPROVAL_JSON`: approval theo source/version chính xác,
  `artifactClass: D4PLANNER_APPLICATION_NO_SNAPSHOT`, `approvedBy: TrdHuy`,
  `approvalRef`, `publicDistributionApproved: true`, `licensesVerified: true`.
  Đây là quyền phân phối application/dependencies; không phải quyền snapshot.

`inputs-manifest.json` có schema `d4planner-public-build-inputs/v1`,
`snapshotIncluded: false`, runtime versions và inventory SHA của mọi file.
Archive/manifest/runtime trees phải khớp pin trong source; chỉ chấp nhận roots
python/node/chromium/nsis. Source Rule Kit dùng allowlist; npm dependencies dùng
lockfiles và reviewed tree digest. Content inspection chặn private manifest,
profile, known snapshot payload đổi tên, encrypted/unreviewed archive và DB.
Không download/mount snapshot private trong public build, cache, log hay artifact.

Versions: Python 3.12.10, Node 22.22.1, Rust 1.90.0, NSIS 3.09,
Chromium 156.0.8078.4, Playwright Core 1.64.1. Cargo/npm dùng lockfiles;
BE dùng requirements-release.txt. Không tải latest hoặc dependency lúc launch.

## Build-only

`release_ci.py` verify public inputs → build FE/root → BE wheel/site-packages →
Rule Kit dependencies → assemble stage → package → NSIS Setup. Scripts hiện có
được tái sử dụng. Verify manifest/SHA/public content và chạy real runtime probe
FE → Backend → Node/Chromium → WS, xác nhận calculation UNAVAILABLE khi không
có snapshot, owned cleanup. Probe không thay native visual acceptance.

Artifact chỉ gồm Setup EXE + release-metadata.json + SHA256SUMS, không upload
inputs/cache/raw DB/private snapshots/log/credentials. `build_only=true` không
tạo GitHub Release. Build/upload vẫn cần application license/distribution approval.

## Publish opt-in

`build_only=false` giữ đúng artifact đã build/test, không rebuild; chờ protected
`d4planner-release` environment có reviewer TrdHuy, prevent self-review. Thiếu
quyền/gate/environment thì dừng an toàn; không tự tạo hoặc cấu hình environment.

`D4PLANNER_RELEASE_GATES_JSON` bind exact sourceHead/version/Setup SHA, Owner và
approvalRef. PKG-01…08, HUD-03, VISUAL_GOLDEN, SNAP-01…07 phải PASS. Hiện production
trust, real multiple-snapshot evidence, MAN/Golden chưa đầy đủ nên **không
release-ready**. Network-off negative vẫn DEFERRED_OWNER.

Download đúng immutable artifact ID, verify checksum/metadata/gates/approval,
từ chối tag/release tồn tại. Không publish trong đợt này. Không đưa snapshot vào
application attestation hoặc dùng approval application để vượt quyền snapshot.
