# Issue #48 — Multistream Core Architecture

## Mục tiêu

Issue #48 cung cấp backend multistream với **một core logic duy nhất**. HTTP và WebSocket chỉ là transport/entry point; không sở hữu business logic, state machine, vendor mapping hoặc lifecycle riêng.

## Dependency rule

```text
HTTP entry point ─┐
                  ├──> Multistream Core/Service ──> Repository
WS entry point ───┘             │
                                ├──> EventBus
                                └──> MultiRtmpAdapter ──> OBS WebSocket ──> obs-multi-rtmp
```

Dependency chỉ đi theo chiều vào Core. Core không import HTTP/WebSocket transport.

## Folder architecture đích

```text
streamops/
├── api/v1/multistream/
│   ├── http.py
│   ├── websocket.py
│   └── schemas.py
├── multistream/
│   ├── models.py
│   ├── states.py
│   ├── commands.py
│   ├── events.py
│   ├── errors.py
│   ├── service.py
│   ├── repository.py
│   ├── event_bus.py
│   └── adapters/
│       ├── base.py
│       └── multi_rtmp.py
└── obs/
    └── ...

tests/
├── unit/multistream/
├── contract/multistream/
│   ├── test_http.py
│   └── test_websocket.py
└── e2e/multistream/
```

Tên/path thực tế có thể map theo convention hiện hữu của repo, nhưng boundary trên là bắt buộc.

## Core

Core sở hữu public `destination_id`, mapping nội bộ `destination_id ↔ plugin target_id`, lifecycle `IDLE / STARTING / LIVE / RECONNECTING / STOPPING / FAILED`, validation, idempotency, error model, credential redaction và reconciliation sau OBS/WebSocket reconnect/restart.

Service/use cases dùng chung:
- `list_destinations()`
- `get_destination(id)`
- `create_destination(command)`
- `update_destination(id, command)`
- `delete_destination(id)`
- `start_destination(id)`
- `stop_destination(id)`
- `get_status(id)`
- `get_stats(id)`

Không tạo business function riêng kiểu `start_http()` hoặc `start_ws()`.

## HTTP transport

HTTP chỉ:
1. parse/validate transport payload;
2. map request thành Core command/query;
3. gọi Multistream Service;
4. serialize result/error thành HTTP response.

HTTP không gọi `CallVendorRequest` trực tiếp, không quản lý plugin target ID, không tự normalize lifecycle/idempotency và không giữ state riêng.

REST scope giữ semantics của issue #48 dưới `/api/v1/multistream/destinations`.

## WebSocket transport

Endpoint dự kiến:

```text
WS /api/v1/multistream/ws
```

WS hỗ trợ initial snapshot sau connect/reconnect và realtime domain events: state, stats, CRUD và structured runtime errors.

Event envelope tối thiểu:

```json
{
  "type": "destination.state_changed",
  "timestamp": "2026-10-07T05:50:00Z",
  "destination_id": "youtube",
  "data": {
    "previous_state": "STARTING",
    "state": "LIVE"
  }
}
```

Event types dự kiến:
- `multistream.snapshot`
- `destination.created`
- `destination.updated`
- `destination.deleted`
- `destination.state_changed`
- `destination.stats_updated`
- `destination.error`

Nếu WS nhận command từ client, command đó phải map vào **cùng Core use case** mà HTTP sử dụng.

## Event flow

```text
HTTP/WS command
      │
      ▼
Multistream Service
      │
      ├── state/repository
      ├── adapter
      └── domain event
             │
             ▼
          EventBus
             │
             ▼
       WS broadcaster
             │
             ▼
             FE
```

Core chỉ publish domain event; Core không biết WebSocket client hay wire format.

## Adapter boundary

`MultiRtmpAdapter` là nơi duy nhất của multistream được biết Vendor protocol:

```text
Multistream Core
      ↓ adapter interface
MultiRtmpAdapter
      ↓
OBS WebSocket / CallVendorRequest
      ↓
sorayuki.multi_rtmp
```

Vendor ACK như `start_requested` không được coi là `LIVE`.

## Source of truth

HTTP query và WS event/snapshot lấy từ cùng Core state/repository. Không tồn tại HTTP state model và WS state model riêng.

Khi WS client reconnect, server gửi snapshot Core hiện tại trước rồi mới tiếp tục delta events.

## Testing strategy

### UNIT
Test Core độc lập transport: CRUD/validation, identity mapping, lifecycle, idempotency, error normalization, secret redaction, reconciliation và domain events.

### CONTRACT
HTTP và WS chỉ test transport mapping. Cùng operation qua HTTP/WS phải tạo cùng Core behavior, state transition, validation, normalized error semantics và domain-event semantics.

### E2E
`HTTP/WS → Core → fake adapter`: cover lifecycle, reconnect, OBS restart simulation, preflight failure và credential redaction.

### Real-A / Dev F
Acceptance trên A dùng OBS/plugin thật. Không gọi Python/Vendor runner trực tiếp để thay thế public API.

## Security

Credential/stream key không được xuất hiện trong HTTP response, WS event, error, log hoặc evidence.

## Dependency #47

Core preflight sử dụng capability từ OBS Plugin Manager (#47) để xác nhận plugin installed/supported, OBS ready, obs-websocket connected và Vendor available. Transport chỉ serialize normalized service-not-ready error, không tự probe plugin.

## Definition of Done bổ sung cho #48

- [ ] HTTP và WS đều là thin entry point.
- [ ] Không có Vendor/plugin business logic trong HTTP/WS handler.
- [ ] HTTP và WS gọi cùng Multistream Service/Core use cases.
- [ ] HTTP GET và WS snapshot/event có cùng source of truth.
- [ ] WS reconnect nhận initial snapshot rồi mới nhận delta events.
- [ ] Core không phụ thuộc HTTP/WebSocket implementation.
- [ ] Contract tests chứng minh transport parity.
