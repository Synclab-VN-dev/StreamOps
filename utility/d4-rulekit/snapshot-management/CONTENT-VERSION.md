# Snapshot Content Version Detection — SVER-01…05

Owner requirement: PR #146 comment 6440052644, 27/10/2026. Implementation thuộc
Rule Kit; không có network/capture/scheduler, registry compatibility hoặc activation.
Eight Application APIs giữ nguyên. `compareSnapshots` là additive method của
`d4-rulekit-snapshots/v1`; result có `contentVersionContract=d4-rulekit-content-version/v1`.
Các methods Management cũ/namespace cũ không bị đổi nghĩa.

## Scope đã rà soát

Capture hiện có: `providers/maxroll/src/snapshot-capturer.js` dùng
BrowserInfrastructure/WebSnapshotManager, GET/HEAD anonymous, allowlist
`https://maxroll.gg`, `https://assets-ng.maxroll.gg`, `https://planners.maxroll.gg`;
loại resource type media và exact path `planners.maxroll.gg/users/whoami`.
Service workers/WebSocket bị block; default response policy bỏ sensitive fields
và chỉ lưu sanitized headers. Navigation/settle dùng domcontentloaded; interaction
đọc patch và danh sách export JS khi nút New Profile hiện. Không Save/Publish.

Manifest `web-snapshot/v1` lưu URL/method/body SHA/size và integrity anchor, nhưng
**không lưu toàn bộ policy, resource types hoặc discovery graph/completion proof**.
`resource-inventory.json`/capture report cũ cũng không đủ để tự suy graph COMPLETE.
Không sửa/đóng dấu COMPLETE hồi tố cho snapshot ngày 23/10. Baseline thiếu coverage
được trả UNVERIFIED, dù tất cả blobs verify. Completeness chỉ trong navigation và
interaction profile đã định nghĩa, không có nghĩa đã capture toàn website hoặc
mọi dynamic state có thể xảy ra.

## Scoped Resource Inventory contract

Schema: `schemas/content-version.schema.json`, definitions scope/coverage/snapshot/
compareParams/compareResult. API nhận hai snapshot refs trong store do Manager sở
hữu, không nhận arbitrary filesystem paths, URL để fetch hay content hashes tự khai
thay cho verified manifest. Scope là descriptor dữ liệu, không executable callback.

Scope gồm policy ID/version + SHA của toàn bộ capture-policy definition, origins,
GET/HEAD methods, include/exclude rules (origin + EXACT/PREFIX path), excluded
resource types, navigation/interaction profile ID/version/definition SHA,
request-header/response policy, service-worker/navigation/settle policy và URL
normalization version. Definition hashes phải bind chính cấu hình/filter/interaction
đã áp dụng; không được đổi IDs giữ nguyên hash khi đổi semantics. Đổi scope/policy
thì UNVERIFIED/SCOPE_POLICY_MISMATCH, không NEW_VERSION_FOUND hoặc UNCHANGED.

URL normalization tái sử dụng validateSafeUrl: WHATWG URL, lowercase host/default
port normalization, drop fragment; **giữ nguyên path/query và thứ tự/duplicate query
parameters**, kể cả cache-busting hash. Không fuzzy-match tên hoặc strip query
heuristic. Identity là `METHOD + space + normalized URL`. Origins/methods/rules là
sets được canonical sort/dedupe. Duplicate identity cùng hash được collapse; hash
hoặc resource-type conflict là typed error. Store hiện tại đã reject duplicate keys.

Coverage offline có manifest SHA + scope fingerprint, evidence ID, roots, observed
nodes (method/URL/resourceType), dependency edges, navigation/interaction/discovery
completion, pending count và failed requests. Rule Kit kiểm tra binding, manifest allowedOrigins phải khớp scope origins, source
root, graph endpoints/reachability, discovered-vs-stored coverage và body status.
Thiếu graph/node/blob, pending/failed in-scope request hoặc HEAD/304/error response
không chứng minh được entity body: UNVERIFIED hoặc typed store integrity error.
Outside-scope/media nodes không được biến thành missing in-scope resources.

Coverage là **offline producer evidence**, không phải production trust/approval.
Caller chịu trách nhiệm provenance đúng của discovery/profile; graph tự dựng chỉ
từ các manifest rows không chứng minh capture đủ. Không coi local COMPLETE hoặc
APPROVED flag là proof: schema không có flag COMPLETE, và các checks trên vẫn bắt
buộc. Không có cryptographic attestation mới hoặc thay production trust policy.

## Fingerprint và diff

1. FileSystemSnapshotStore.load/verify/load kiểm tra manifest anchor, expected
   manifest pin, tất cả blobs/size/SHA và manifest ổn định trong lần đọc.
2. Lọc đúng scope; canonical sort theo identity bằng code-unit order, không dùng
   locale-dependent order. Resource types dùng coverage evidence để loại media;
   thiếu type/coverage không được kết luận toàn graph COMPLETE.
3. SHA-256 của UTF-8 canonical JSON:

```text
{domain:"d4-rulekit-snapshot-content/v1",
 scopeFingerprint:SHA256(canonical(normalizedScope)),
 resources:[{method,url,sha256}, ... sorted by identity]}
```

Không dùng manifest/resourceInventory SHA làm content fingerprint. Snapshot ID,
capturedAt, browser/Playwright metadata, ordering, headers/cache/status và manifest
formatting không vào hash. Fingerprint của observed partial set vẫn tính được,
nhưng được gắn OBSERVED_SCOPED_CONTENT; không phải complete version attestation.

Chỉ khi hai scopes bằng nhau và cả hai coverage COMPLETE mới trả confirmed diff:
ADDED (oldSha=null), REMOVED (newSha=null), MODIFIED (cùng identity, hash khác).
Rename filename/URL tạo removed+added và fingerprint mới dù bytes JS không đổi.
Mọi in-scope JS/CSS/font/image/data/wasm được tính, không chỉ engine/catalog.

Thiếu coverage: status UNVERIFIED, `diff=null`; `observations` chỉ báo baselineOnly,
candidateOnly/differentBytes của verified captured sets, **không khẳng định xóa/thêm
trong graph đầy đủ**. Scope khác: observations cũng null. Không phát minh REMOVED
vì capture thất bại. Integrity/pin/schema conflict trả typed error, không UNCHANGED.

## API / examples

```text
Manager.invoke("compareSnapshots", {
 baseline:{snapshotId, manifestSha256, scope, coverage},
 candidate:{snapshotId, manifestSha256, scope, coverage}
})
```

coverage có thể omitted/null để kiểm tra legacy offline package một cách trung thực.
Node CLI hiện có `manage.js --operation compareSnapshots --data-root ...
--installation-root ... --request-file ... --report ...` dùng đúng namespace và
same schemas. Python Rule Kit IPC transport thêm whitelist method, không đặt logic
trong BE/FE. Manager dùng bounded serial queue hiện có; chỉ đọc, không đổi selection,
registry/profile, worker generation, session/cache hoặc promote snapshot.

Examples rút gọn (full response schema ở compareResult):

```json
{"status":"NEW_VERSION_FOUND","reason":"SCOPED_CONTENT_CHANGED",
 "fingerprintKind":"COMPLETE_SCOPED_CONTENT","scopeComparable":true,
 "diff":{"summary":{"added":1,"removed":1,"modified":0},"resources":[]}}
```

`resources` thực tế chứa hai rows URL Planner cũ/mới, old/new SHA; ví dụ trên lược
bỏ rows và provenance cho gọn, không phải fixture/acceptance evidence.

```json
{"status":"UNVERIFIED","reason":"COVERAGE_UNVERIFIED",
 "fingerprintKind":"OBSERVED_SCOPED_CONTENT","diff":null}
```

Fingerprint bằng nhau + COMPLETE → UNCHANGED/SCOPED_CONTENT_IDENTICAL.
Fingerprint khác + COMPLETE → NEW_VERSION_FOUND; engine/catalog bằng nhau vẫn NEW
khi Planner module đổi. Không có phép suy Runtime Compatibility từ ba statuses này.

## Acceptance / tests

| Gate | Evidence |
|---|---|
| SVER-01 | Scope/path/media exclusion; profile/policy mismatch; graph completeness/bindings; legacy UNKNOWN |
| SVER-02 | Stable independent expected SHA, metadata/format/order ignored, query preserved, duplicate conflicts |
| SVER-03 | Added/removed/modified, same-byte Planner rename, Planner-only change while engine/catalog unchanged |
| SVER-04 | Real JSON schemas, actual Node worker IPC/correlation/generation, read-only no-trust comparison |
| SVER-05 | Integrity/schema/pin/304/HEAD/error negatives and legacy integrity/trust/eight Application API regressions |

`node --test utility/d4-rulekit/snapshot-management/tests/*.test.js` dùng synthetic
offline packages, không capture/live-provider approval. Các tests SVER **không**
thay evidence SNAP-05 switch/rollback failure-path riêng. Limits theo existing store
(5000 resources/256MiB), scope rules 64, graph 20000 edges; không unbounded crawl.
