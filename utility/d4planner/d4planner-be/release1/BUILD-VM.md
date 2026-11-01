# Build Setup trên Windows VM, nhận artifact trên F

Host wrapper: `tools/build_setup_vm.py`; guest runner: `tools/build_setup_vm.ps1`.
Host chỉ cần Python 3.11+, Git, OpenSSH `ssh`/`scp`. Không cần Docker hoặc PowerShell
trên F. Đây là wrapper cho **VM đã chạy và đã cấu hình SSH**, không phải VM provisioner.

## Chuẩn bị VM một lần

VM build Windows x64 cần:

- OpenSSH Server, SFTP và đăng nhập bằng key từ F; host key đã được xác minh/lưu
  trong known_hosts. Wrapper dùng BatchMode và StrictHostKeyChecking, không hỏi
  password hoặc tự chấp nhận host key.
- Git for Windows, Python **3.12.10**, Node **22.22.1** (`npm.cmd` trên PATH).
- Rust **1.90.0** MSVC toolchain, Visual Studio C++ x64 Build Tools và Windows SDK.
- Internet để tải đúng dependency/runtime pins của Release CI. Python build venv
  được tạo riêng mỗi run; không pip install vào Python hệ thống. Không cần `gh`
  hoặc GitHub token trong VM vì đây chỉ là build-only.

VM local đã dùng cho test hiện khởi động với `-nic none`, **chưa có SSH transport**.
Muốn dùng wrapper với VM đó phải cấu hình network/SSH trước. Với QEMU, dùng NAT
và host port forwarding chỉ bind `127.0.0.1`, không bridge ra LAN. Chọn port còn
trống cho VM riêng; wrapper không tự đổi VM launcher, firewall hoặc SSH config.

Hướng dẫn Microsoft:
[cài OpenSSH Server](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse),
[cấu hình public key](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).

Đặt SSH alias trong `~/.ssh/config` trên F, ví dụ (thay port/user/key theo VM):

```sshconfig
Host d4planner-builder
    HostName 127.0.0.1
    Port <VM-forwarded-port>
    User <VM-build-user>
    IdentityFile ~/.ssh/<VM-build-key>
    IdentitiesOnly yes
```

Kiểm tra transport/key bằng `ssh d4planner-builder whoami` trước. VM/account này
chỉ dùng cho build; wrapper không cần quyền Administrator khi build.

## Một lệnh trên F

Từ root repository, kiểm tra toolchain trước:

```bash
python3 utility/d4planner/d4planner-be/tools/build_setup_vm.py \
  --vm d4planner-builder --check \
  --output "$HOME/d4planner-builds/check-$(date +%Y%m%d-%H%M%S)"
```

Build commit hiện tại và lấy artifact:

```bash
python3 utility/d4planner/d4planner-be/tools/build_setup_vm.py \
  --vm d4planner-builder \
  --ref HEAD --version 1.2.8 \
  --output "$HOME/d4planner-builds/setup-$(date +%Y%m%d-%H%M%S)"
```

`--repo` mặc định là repository chứa wrapper. `--ref` là local commit/ref đã có
trên F; không tự fetch/pull. Chỉ source **đã commit** được chuyển, không lấy staged,
unstaged, untracked hoặc ignored files. Có thể bỏ `--version` để lấy version từ
package-plan của commit đã chọn. Nếu nhập version thì phải khớp plan.

`--python 'C:/path/to/python.exe'` chọn Python trong VM nếu chưa có trên PATH.
`--timeout 5400` thay deadline mặc định 3600 giây. Output phải là thư mục mới;
không ghi đè kết quả cũ.

## Pipeline và output

Wrapper tạo shallow Git checkout riêng, giữ nguyên commit HEAD và bytes LF;
truyền ZIP và guest script qua SCP. Guest xác minh hash source trước khi giải nén.
Trong thư mục `%TEMP%/d4planner-build-<uuid>` riêng, guest tạo venv và gọi đúng:

1. `release_ci.py validate` với `D4_BUILD_ONLY=true`.
2. `release_ci.py build`: compile, tests, staging, NSIS Setup, runtime health.
3. `release_ci.py prepare-upload` và `validate-upload`: kiểm tra artifact.

Không gọi publish, tạo tag/Release hoặc upload GitHub. Không chỉnh checkout có sẵn
trong VM. Không tự cài MSVC/Node/Rust/SSH; preflight báo thiếu trước khi build.

Khi thành công, thư mục output trên F có:

```text
D4Planner-Setup-1.2.8.exe
SHA256SUMS
release-metadata.json
UAT.md
build.log
transport.log
preflight.log
connection.log
result.json
run.json
```

Host chỉ lấy bốn artifact có tên xác định và hai file diagnostics, không copy
recursive runtime/source/private VM directories. SHA-256 của từng file và
source/version/size/class/runtimeHealth trong metadata đều được kiểm tra lại.
Download lỗi hoặc hash sai nằm trong `download/`, không được promote thành Setup
thành công. Exit 0 chỉ khi build và xác minh cuối đều PASS; `--check` exit 0 chỉ
có nghĩa preflight PASS, không phải đã build.

Build lỗi vẫn lấy `build.log`/`result.json` nếu transport còn hoạt động. Mất SSH,
timeout hoặc Ctrl-C sẽ thử dừng đúng cây process của run, đối chiếu PID và thời
điểm khởi động trong owner record. Nếu không kết nối lại/xác minh được cleanup,
wrapper báo rõ; không tuyên bố process đã dừng. Giữ run directory để debug,
đường dẫn nằm trong `run.json`; không tự xóa các run khác. Wrapper không tắt VM.

## Mức evidence

Unit tests kiểm tra snapshot Git thật, orchestrator với SSH giả lập, checksum,
failure/cancel, và không ghi đè output. Chúng không chứng minh SSH Windows hay
Setup runtime PASS. Full build qua SSH chỉ được coi PASS khi wrapper thực sự kết
thúc exit 0 với artifact đã xác minh. Một compile PASS không thay native health
check hoặc các gate Owner/Visual.
