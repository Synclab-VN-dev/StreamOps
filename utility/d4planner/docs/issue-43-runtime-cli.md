# Issue #43 — D4Planner Runtime Supervisor + CLI

Branch implementation scaffold for #43.

## Goal

Turn the NVDA capture POC from #39 / #41 into a production-style runtime with a thin CLI:

```text
d4planner CLI
    ↓
D4Planner Supervisor (Windows A)
    ├─ NVDA runtime
    ├─ Steam / Diablo IV lifecycle
    └─ Session + unified event stream
```

Primary UX:

```bash
d4planner start
d4planner status
d4planner logs
d4planner stop
d4planner doctor
```

The implementation must remain SSH-friendly from machine B / Termux.

## Runtime contract

- Runtime root: `%LOCALAPPDATA%\d4planner`
- Do not copy controller DLLs into the Diablo IV directory.
- Production mode manages the controller runtime in User PATH only; Machine PATH must remain unchanged.
- User PATH changes must be idempotent and reversible.
- Detect stale Steam environment instead of pretending capture is ready.
- Never force-kill Diablo IV or Steam by default.
- NVDA must run in the active interactive console session.
- `Tolk_DetectScreenReader() == NVDA` is required before `CAPTURE_READY`.

## Capture behavior

Default runtime mode is silent capture:

```text
D4/Tolk
  ↓
NVDA speech
  ↓
D4Planner filter
  ├─ persist/stream raw event
  └─ D4 + silent mode → return []
```

Rules:

- suppress only when the source/context is confidently Diablo IV;
- uncertain/non-D4 speech always passes through;
- `d4planner start --speech` keeps normal NVDA speech for debugging;
- avoid double capture when migrating from `pre_speech` to `filter_speechSequence`.

## Session model

Each capture lifecycle creates its own immutable session:

```text
%LOCALAPPDATA%\d4planner\sessions\<timestamp>-<session-id>\
├── metadata.json
├── events.jsonl
└── runtime.log
```

Do not clear/truncate prior raw evidence.

Runtime and speech records share one monotonic event stream so future CLI, Web UI, parser, and OBS overlay can consume the same source.

## Safety

This branch must not add:

- D4 RAM/process-memory reading;
- DLL injection;
- DirectX/game hooks;
- game-directory modifications;
- automated gameplay input;
- default force-kill behavior for D4/Steam.

## Verification gates

Implementation and merge are governed by the detailed checkbox matrix in issue #43:

1. Unit / CI
2. E2E / CI
3. Dev F / Real-A on Windows A
4. Operator / UAT

Technical failures must be resolved by Gate 3; operator UAT should only validate real UX/gameplay behavior.

Refs: #43, #39, #41.
