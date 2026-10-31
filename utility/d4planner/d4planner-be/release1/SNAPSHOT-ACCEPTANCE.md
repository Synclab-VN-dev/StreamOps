# Snapshot split — acceptance theo quyết định Owner 27/10/2026

Đây là contract bổ sung thuộc Rule Kit/S7; không thay tám Application APIs,
canonical schema, Equipment policy hoặc approved snapshot pin. Các operating
semantics và Ed25519 trust design đã APPROVED. Production trust activation vẫn
BLOCKED cho tới khi Owner cấp verification key/key ID; không tự ký production.

| ID | Điều kiện | Evidence cần có và ranh giới |
|---|---|---|
| SNAP-01 | Setup không chứa private snapshot/profile, plaintext hoặc encrypted | Public input tree/source allowlist, negative content inspection, verify toàn bộ ZIP trước NSIS; Setup dùng đúng ZIP và bootstrap Python đã kiểm tra |
| SNAP-02 | No-snapshot FE/BE/Equipment hoạt động; calculation UNAVAILABLE | Real Node/Chromium lifecycle + managed BE/SQLite/WS; Windows root runtime-health/native launch tách khỏi synthetic tests |
| SNAP-03 | Một Rule Kit build nhận diện nhiều verified snapshots | Hai synthetic signed packages qua cùng resolver và real Node IPC: TEST_ONLY; ít nhất hai real approved packages mới đủ real-provider acceptance |
| SNAP-04 | Unknown/corrupt/revoked/incompatible bị reject, không fallback | Registry signature/revision/expiry/revocation, exact profile/codec/strategy/hash, isolated negative tests; production thiếu anchor phải reject import |
| SNAP-05 | Switch/rollback invalidate sessions/cache/generation, giữ DB | Real Node IPC generation chuyển, old session reject, bounded reconfigure tách crash budget; synthetic inputs không chứng minh real provider compatibility |
| SNAP-06 | Upgrade/uninstall giữ store/data; incompatible active fail closed | Engine rejection giữ app pointer/DB; Windows Setup upgrade/uninstall giữ external store sentinel; legacy bundled snapshot cần trusted migration |
| SNAP-07 | Public CI không chứa snapshot, private evidence bind exact hashes | Public-only archive pin trước download, policy inventory/content negatives, exact Setup/source checks; actual Actions NOT_RUN và real provider integration chờ official anchor/registry |

Commands local (source tests, không tự nhận Windows/production PASS):

```text
node --test utility/d4planner/d4planner-rulekit/snapshot-management/tests/*.test.js
PYTHONPATH=utility/d4planner/d4planner-be/src python -m pytest -q utility/d4planner/d4planner-be/tests/test_snapshot_worker.py utility/d4planner/d4planner-be/tests/test_snapshot_backend.py utility/d4planner/d4planner-be/tests/test_public_package.py utility/d4planner/d4planner-be/tests/test_windows_install.py utility/d4planner/d4planner-be/tests/test_release_ci.py
```

Native UAT dùng runner hiện có `windows_installer_review_e2e.py` qua đúng task,
port, sandbox được Owner duyệt. PKG cases kiểm tra application no-snapshot;
opaque synthetic store sentinel chỉ chứng minh bảo toàn file, không phải trusted
real snapshot. Provisioned mode phải có production trust anchor và exact approved
registry/profile/snapshot. Thiếu điều kiện đó: BLOCKED/NOT_RUN đúng phần đó.

Rule Kit schema/API: `utility/d4planner/d4planner-rulekit/snapshot-management/{README.md,schemas}`.
BE chỉ forward private `rulekit.snapshot`, không resolve registry. FE dùng health
hiện có, không thêm snapshot/profile selector hoặc đổi MagicPath. PKG-08/HUD-03
Owner MAN; independent Visual Golden BLOCKED; offline negative DEFERRED_OWNER.
