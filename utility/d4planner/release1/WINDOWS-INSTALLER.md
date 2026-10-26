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
