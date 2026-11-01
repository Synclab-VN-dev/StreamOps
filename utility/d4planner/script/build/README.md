# Build Setup bằng Windows VM từ F

Từ root checkout/worktree, chạy một lệnh:

```bash
python3 utility/d4planner/script/build/build_vm.py
```

Output mặc định: `~/d4planner-builds/<timestamp>-<id>/`. Khi thành công, wrapper
in đường dẫn `D4Planner-Setup-<version>.exe`. Không lấy binary ứng dụng từ GitHub
Actions: Launcher, HUD/Tauri và BE được build từ source chuyển sang VM.

## VM trên F

Builder riêng đã được clone từ VM test, có disk/UEFI/TPM riêng. OpenSSH dùng key,
NAT và host forwarding chỉ trên loopback; không dùng Windows A/production.
Thông tin enrollment nằm ngoài repository:

```text
~/.local/share/streamops/d4planner-builder/
  config.json
  ssh_config
  known_hosts
  id_ed25519
  start-vm.py
  windows.qcow2
```

Wrapper đọc `config.json`, giữ khóa độc quyền giữa các worktree và tự khởi động
VM nếu chưa chạy. Chỉ tắt VM khi chính lượt chạy này đã khởi động nó. VM đang chạy
sẵn được giữ nguyên. SSH luôn xác minh host key; không tự accept key lạ.

Trên một host khác, Windows OS/license và SSH enrollment phải có một lần; script
không tự tạo Windows OS hoặc tin host key chưa xác minh. Có thể dùng alias SSH
riêng với `--vm <alias>`; VM ngoài enrollment cần đang chạy. File config có format:

```json
{
  "schemaVersion": 1,
  "dedicatedBuilder": true,
  "alias": "d4planner-builder",
  "sshConfig": "/absolute/path/ssh_config",
  "startCommand": ["python3", "/absolute/path/start-vm.py"]
}
```

Host cần Python 3.11+, Git và OpenSSH. Build account trong VM riêng cần admin
cho lần đầu cài MSVC/SDK. Không cần GitHub token/credential để build.

## Source và version

Mặc định gửi source **hiện tại**, gồm staged, unstaged và untracked không bị
Git ignore; giữ cả thao tác xóa file. Không gửi `.git` của worktree đang dùng,
ignored dependency/cache/output, hoặc untracked file có tên private key phổ biến.
Developer phải gitignore các secret/local artifacts của mình; wrapper không thể
nhận diện mọi loại secret theo nội dung.

Wrapper tạo checkout tạm. Nếu source khác HEAD, nó tạo commit snapshot **chỉ trong
checkout tạm**, không commit/stash/reset repository của developer. `source.json`
ghi base HEAD, snapshot HEAD và tree hash; release metadata dùng snapshot HEAD.
Source được chụp trước khi setup lâu, nên chỉnh sửa tiếp trên F không thay đổi
lượt build đang chạy. Không sửa source đồng thời trong thời gian chụp snapshot.

Muốn chỉ build một commit cụ thể: `--ref HEAD` hoặc `--ref <SHA>`.
Version tự lấy từ `release1/package-plan.json`. `--version` nếu truyền phải khớp
plan trong source đã chụp; không liên quan GitHub secret hay Release đã tồn tại.

## Setup, build, teardown

1. Kiểm tra toolchain, tự cài phần thiếu: Python 3.12.10, Node 22.22.1, Git,
   Rust 1.90.0 MSVC, Visual Studio C++ và Windows SDK. Download HTTPS, kiểm tra
   SHA-256 theo `toolchain-lock.json`. Dùng lại Python đăng ký đúng phiên
   bản thay vì cài lại. Frameworks được giữ qua các lần build.
2. Gửi snapshot qua SCP, xác minh SHA-256 và Git HEAD trên VM. Tạo venv, source,
   staging và TEMP riêng dưới `C:\D4Builder\runs\d4planner-build-<uuid>`.
3. Chạy `release_ci.py validate`, `build`, `prepare-upload`, `validate-upload`
   với `D4_BUILD_ONLY=true`: cùng compile/test/staging/NSIS/runtime-health pipeline
   như Release CI. Không publish, tạo tag/Release hoặc query GitHub Actions.
4. Tải bốn artifact và diagnostics về F; kiểm tra checksum/source/version/class/
   runtimeHealth. Chỉ promote Setup sau khi xác minh đủ.
5. Xóa source, venv, staging, temporary files của đúng run sau khi nhận kết quả.
   Không xóa framework hoặc run khác. Timeout/disconnect thử kill đúng process
   tree theo PID + start time; nếu không xác minh được cleanup thì báo lỗi và
   giữ run để xử lý, không xóa khi process có thể còn chạy.

Normal build giữ Cargo compilation cache và cache download pip/npm để dùng lại.
`--rebuild` xóa Cargo compilation cache trước build; framework, runtime pin và
package download cache vẫn giữ. Cả hai mode đều dọn temporary run directory.
Public Python/Node/Chromium/NSIS runtime inputs được cache theo hash runtime lock,
và **xác minh lại toàn bộ pins mỗi lần dùng**. Installed product paths không đổi.

```bash
# Compile lại từ cache sạch; không cài lại framework
python3 utility/d4planner/script/build/build_vm.py --rebuild

# Chỉ setup phần thiếu, không build
python3 utility/d4planner/script/build/build_vm.py --setup-only

# Chỉ kiểm tra, không cài toolchain
python3 utility/d4planner/script/build/build_vm.py --check

# Chọn output mới; thư mục đã tồn tại bị từ chối
python3 utility/d4planner/script/build/build_vm.py --output "$HOME/d4planner-builds/my-build"
```

Lần đầu tải/cài framework và compile dependency sẽ lâu hơn các lần sau.
`--timeout` mặc định 10800 giây cho mỗi pha setup/build; đây là deadline, không
phải thời gian dự đoán. Log ở output directory cập nhật trong lúc chạy.

## Output và mức evidence

```text
D4Planner-Setup-<version>.exe
release-metadata.json
SHA256SUMS
UAT.md
source.json
result.json
build.log
transport.log
preflight.log
connection.log
cleanup.log
timing.log
timing.json
run.json
```

Build lỗi vẫn lấy build.log/result.json nếu SSH hoạt động. Output tải chưa xác
minh nằm trong `download/`, không được tuyên bố thành công. `--check`/`--setup-only`
PASS chỉ xác nhận toolchain, không phải Setup build PASS. Unit tests mô phỏng SSH
không thay thế Windows-native build. Full build chỉ PASS khi exit 0 và artifact
đã qua checksum + native runtime health. Owner MAN/Visual/release gates độc lập.

### Thời gian build

Terminal và `timing.log` ghi timestamp UTC, thời gian từng pha và dòng `TOTAL`
sau cleanup/shutdown. `timing.json` chứa `totalSeconds`, thời gian/trạng thái từng
pha để so sánh performance giữa các lượt. Thời lượng dùng monotonic clock, không
bị sai khi đồng hồ hệ thống được đồng bộ lại. Tổng bao gồm chuẩn bị source, bật/kết
nối VM, setup, upload, build, download/verify, cleanup và shutdown; log vẫn được
kết thúc khi build lỗi. `--check`/`--setup-only` chỉ đo các pha thực sự được chạy.

### Source layout

`build_vm.py` là entrypoint trên F, bao gồm quản lý VM và timing.
`windows_build.ps1` gộp setup toolchain và build trong Windows; cấu hình pin nằm
ở `toolchain-lock.json`. Tests ở `tests/`. Pipeline release hiện có vẫn là
`utility/d4planner/d4planner-be/tools/release_ci.py`; wrapper chỉ điều phối nó.
