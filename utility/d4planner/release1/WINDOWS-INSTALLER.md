# Bộ cài Windows D4Planner R1

## Trước → Sau

| Thành phần | Trước | Sau |
|---|---|---|
| Phân phối | Portable ZIP, lệnh Python | `D4Planner-Setup-<version>.exe`, ZIP phụ |
| Khởi động | `app/start-d4planner.ps1` | `D4Planner.exe` ở root, tự bootstrap |
| Lifecycle | Native FE quản lý BE; BE quản lý worker | Giữ nguyên; launcher bao ngoài bằng owned Job Object |
| Upgrade | Đổi thư mục app | Payload bất biến theo version; stage/hash/health/journal/atomic activation |
| Gỡ | Chưa đăng ký Windows | `Uninstall.exe`, Desktop/Start Menu, Installed Apps per-user |
| Dữ liệu | DataDir ngoài app | Giữ DB/Targets/Settings/user files; không restore DB khi rollback |

## Kiến trúc và ownership

NSIS là cơ chế Setup/uninstall duy nhất. Tauri bundler mặc định thay resources
in-place và có luồng uninstall riêng trước upgrade; template NSIS tùy chỉnh ở
S7 gọi `windows_install.py` để dùng payload versioned và recovery journal.
Không bật thêm Tauri installer thứ hai; native FE/S6 không đổi.

`D4Planner.exe` → verify SHA-256 manifest → tạo private bootstrap → native FE
→ managed BE → Rule Kit. Launcher dùng mutex theo installation root để chặn
double-click tạo Backend trùng. FE được spawn suspended, gán Job Object trước
khi resume; Job chỉ chứa process của ứng dụng. Stop dùng named event theo root,
gửi WM_CLOSE tới đúng PID FE, chờ graceful shutdown và thu hồi owned job nếu quá
deadline. Launcher hoạt động độc lập với current working directory/PowerShell.

Mặc định install per-user tại `%LOCALAPPDATA%\Programs\D4Planner`. Setup hỗ trợ
chọn thư mục. DataDir mặc định `%LOCALAPPDATA%\StreamOps\D4Planner`, nằm ngoài
installation. Không tự inject Equipment hay chọn Target synthetic.

Setup xác minh WebView2 có sẵn bằng registry; nếu thiếu thì dừng và giải thích.
Không download dependency, không elevate/admin và không thay global toolchain.
Setup EXE chưa ký Authenticode; Owner cần xem xét chính sách ký trước publish.

## Build

Build root launcher bằng Cargo lock và Windows MSVC target; cung cấp
`--launcher-exe` cho `build_release1_stage.py`. Các runtimes vẫn là input đã pin.
`release1_delivery.py build --version X.Y.Z` tạo ZIP có application/version/schema
metadata. `build_windows_installer.py` verify ZIP rồi compile `installer.nsi`
bằng NSIS 3.09; kết quả có Setup EXE và `setup-build.json` gồm size/SHA/source HEAD.
Không publish artifact private chứa Rule Kit snapshots.

## Cài / nâng cấp / recovery

Chạy Setup mới; mặc định nhận ra thư mục và DataDir đã đăng ký. Downgrade bị từ
chối. Same-version reinstall được phép và verify lại toàn bộ payload.
Engine dừng đúng owned application, extract vào `versions/`, kiểm tra từng hash
và `--installation-health`, lưu launcher/metadata trước activation, rồi atomic
replace `active.json`. Failure quay lại version trước; journal còn lại khi mất
điện/process chết được recovery ở lần chạy Setup tiếp theo.

Engine không migrate DB. Trước install/rollback, SQLite được đọc read-only để
kiểm tra schema compatibility; không dùng `immutable=1`. Nếu không xác minh được
compatibility thì dừng an toàn. Rollback chỉ đổi binaries/metadata, không chép
DB backup đè dữ liệu mới. Các version trước giữ trong installation để recovery.

Lệnh stop cho người dùng: `D4Planner.exe --stop`. Recovery khi Setup bị ngắt:
chạy lại cùng Setup. Advanced rollback: dùng private Python trong `maintenance`
chạy `windows_install.py rollback --root <install> --report <private-report>`.

Uninstall qua Installed Apps hoặc `Uninstall.exe`. Dữ liệu luôn được giữ mặc
định; không có tùy chọn xóa user data trong R1. Chỉ xóa file được manifest xác
nhận là application-owned; file người dùng đặt thêm trong install vẫn giữ lại.

## Acceptance tự động và PKG-08 Owner MAN

`windows_setup_e2e.py` chạy Setup production thật, visible HWND, process tree,
duplicate launch, upgrade khi đang chạy, reinstall/downgrade, fault activation,
recovery, integrity negative và uninstaller/data preservation. Report ghi SHA,
expected/actual/duration. Chạy trong sandbox/desktop/port đã được Owner duyệt.
Fixture engine unit tests không thay Windows-native acceptance.

PKG-08: Owner chạy Setup bằng double-click, kiểm tra chọn thư mục, shortcut,
Installed Apps, mở/đóng HUD bằng shortcut/hotkeys; thử nâng cấp và xác nhận data
cũ còn nguyên. HUD cùng Diablo IV/focus/controller/window_capture vẫn là HUD-03
Owner MAN riêng. Golden MagicPath vẫn cần independent reference; screenshot
Setup/HUD actual không được chuyển thành Golden.

## Review FIX-01/02/03 (27/10/2026)

`/ISOLATED=1` dùng riêng HKCU `Software\Synclab\D4Planner-UAT`, uninstall
identity `SynclabD4PlannerUAT`, Desktop `D4Planner UAT.lnk` và Start Menu
`D4Planner UAT`. Marker `installer-identity.ini` + registered root phải khớp
trước stop/upgrade/uninstall. Một UAT root khác không được chiếm registration.
Production namespace không được đọc/ghi/xóa trong nhánh UAT.

Root launcher mặc định không đọc Equipment DB và xóa các biến capture kế thừa.
Để opt-in khi double-click, tạo `launcher.json` trong DataRoot (ngoài installation):

```json
{
  "schemaVersion": "d4planner-launcher/v1",
  "equipmentRepository": {
    "enabled": true,
    "path": "C:\\absolute\\existing-equipment.sqlite",
    "characterId": "authoritative-character-id",
    "characterDisplayName": "Character display name"
  }
}
```

Path phải tuyệt đối, file hiện có; identity không rỗng, không control characters,
tối đa 160 ký tự. Backend dùng `ReadOnlyEquipmentRepository` đã có; launcher không
initialize/migrate DB. Bỏ file hoặc dùng `{"enabled":false}` trong
`equipmentRepository` để tắt. Không tự lấy Target điền Current.

Static gate `--installation-health` vẫn kiểm tra toàn bộ resource/hash. Sau atomic
activation, engine gọi `--runtime-health --health-report <private-json>`: chính FE
executable chạy managed Backend → real Rule Kit/Chromium → WS READY, restart và
stop. Probe có DataDir/Targets rỗng riêng, không đọc config/DB của user; owned Job
Object, deadline 55 giây và bounded cleanup. Chỉ commit journal khi runtime report
xác nhận READY + cleanup. Failure phục hồi application pointer/launcher trước,
không restore DB. Runtime probe không chứng minh native WebView render (gate riêng).

Windows runner `windows_installer_review_e2e.py` chỉ chạy trong sandbox/task/port
đã duyệt; verify artifact SHAs, scrub PATH cho cả Setup lẫn launcher, kiểm tra
registration/shortcuts giả lập bản chính và rollback runtime-failure với manifest
đã rehash. Không đụng DB/game/OBS thật. Network-off negative vẫn DEFERRED_OWNER.

### Giới hạn staging Windows

Không đổi `LongPathsEnabled` của Windows. UAT dùng staging root ngắn vì một số
resource Playwright có path sâu; trên Windows chưa bật long paths, chọn root
đủ ngắn (mặc định per-user hoặc sandbox ngắn). Một lượt resume với root dài đã
fail extract trước activation, được giữ nguyên evidence; không có runtime hay
registration được commit trong lượt đó. Không lấy failure đó làm PASS.

Targeted resume: wrapper nhận `-CaseIds` và `-ResumeReport`; chỉ retry IDs đã FAIL
trong report trước, cộng fresh-install prerequisite và uninstall/cleanup. Report
là `SCOPED_SUBSET_PASS`, không đổi kết quả FAIL lịch sử thành full PASS. Bản UAT
production sentinel chỉ được tạo khi chưa có registration/shortcut thật.

Release CI và checkpoint public distribution xem [RELEASE-CI.md](RELEASE-CI.md).

## Tách Application / Snapshot (Owner APPROVED 27/10/2026)

Setup 1.1.x không chứa snapshot/profile; Rule Kit source/runtime vẫn được đóng
đầy đủ. `D4Planner.exe` chỉ truyền installation root và DataRoot/rulekit, không
resolve registry/profile. Không có snapshot: Equipment/HUD/WS vẫn hoạt động,
calculation **UNAVAILABLE**; process/Chromium readiness được kiểm tra độc lập.

Provisioning local qua `D4Planner.exe --snapshot-command <method>` với
`--request-file <private-json> --report <private-report>`. Phải đóng application
trước offline provisioning; live management do BE gọi riêng Rule Kit API.
Phương thức: listInstalled, checkCompatibility, getCapabilities, importPackage,
activate, getActive, switchSnapshot, rollback. Đây là contract riêng
`d4-rulekit-snapshots/v1`, giữ nguyên tám Application APIs. Registry import dùng
importPackage với kind REGISTRY; snapshot import dùng packagePath. CLI chỉ kiểm
tra configuration, không báo calculation READY khi worker không chạy.

Rule Kit xác thực Ed25519, exact compatibility evidence/profile/codec/strategy,
revision chống rollback và revocation. Không auto-fallback. Một active binding
mỗi worker generation; switch/rollback yêu cầu worker mới và invalidate session.
Production verification public key đã pin; signed Registry revision2 được xác minh
trong UAT sandbox. Private signing key không đi cùng Setup/CI.
Không đưa test key vào cấu hình production hoặc dùng synthetic compatibility
PASS làm production evidence. Store immutable theo ID/hash, ngoài install root.

Upgrade gọi Rule Kit `upgradePreflight` trước activation. Selected binding không
tương thích/untrusted/corrupt hoặc legacy bundled snapshot chưa migrate được
thì giữ app/data cũ. Không tự chuyển profile/snapshot, không restore DB. Fresh
no-snapshot install/upgrade không yêu cầu key. Uninstall giữ snapshot store,
DB, Targets, Settings. D12/Dfjs real-provider UAT đã có evidence trong approved Rogue fixture scope;
không suy thành mọi class/build. Snapshot Release riêng tại
https://github.com/Synclab-VN-dev/StreamOps/releases/tag/d4planner-snapshots/2026.10.30-r2
. Test-only registries vẫn dùng isolated test keys, không được production trust.
