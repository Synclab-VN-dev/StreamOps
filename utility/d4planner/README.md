# D4Planner runtime

Issues: #39 (capture POC), #43 (runtime/CLI)

D4Planner is an intentionally independent bounded context for Diablo IV build
capture. It must not depend on `streamops.server` or modify the Diablo IV game
directory.

## Runtime flow

```text
Diablo IV
  -> Tolk.dll
  -> nvdaControllerClient64.dll
  -> NVDA 2026.2
  -> d4plannerCapture add-on
  -> session raw-speech.jsonl
  -> D4Planner Supervisor
  -> unified events.jsonl
  -> CLI / future Web UI / OBS consumers
```

The Real-A POC in #39/#41 established that Tolk must discover the official NVDA
controller client. If it cannot, D4 may fall back to SAPI: the user still hears
speech, but the NVDA add-on receives nothing.

## Install for development

PowerShell:

    python -m pip install -e "utility/d4planner[dev]"
    python utility/d4planner/tools/build_nvda_addon.py

The CLI entry point is:

    d4planner

The runtime can self-sync the 0.2.0 add-on from an editable StreamOps checkout.
Packaged deployments may provision the built add-on separately.

## CLI

Primary commands:

    d4planner start
    d4planner status
    d4planner logs -f
    d4planner logs -f --raw
    d4planner stop
    d4planner doctor

Default `start` uses **silent D4 capture**: D4 speech is persisted before NVDA
synthesis and is then suppressed only when the foreground context is confidently
Diablo IV.

To keep normal NVDA audio for debugging:

    d4planner start --speech

To keep controller discovery process-scoped for diagnostics:

    d4planner start --isolated

`Ctrl+C` while following logs detaches only the CLI. The supervisor and capture
remain active. `d4planner stop` stops the planner runtime but does not kill
Diablo IV or Steam.

## Runtime storage

Production runtime state is outside the repository:

```text
%LOCALAPPDATA%\d4planner\
├── runtime\
│   ├── nvda-controller\
│   └── bin\
├── sessions\
│   └── <timestamp>-<session-id>\
│       ├── metadata.json
│       ├── raw-speech.jsonl
│       ├── events.jsonl
│       └── runtime.log
├── state\
└── logs\
```

Each start creates a new session. Prior raw evidence is never cleared or
renumbered.

## Controller discovery / PATH

Normal runtime mode adds:

    %LOCALAPPDATA%\d4planner\runtime\nvda-controller

to **User PATH only**. The operation is idempotent and tracked for reversible
cleanup. Machine PATH is read-only to D4Planner.

Diagnostic restore:

    d4planner path status
    d4planner path restore

If Steam was already running before D4Planner first updated User PATH, its
environment is stale. D4Planner reports `RESTART_REQUIRED` instead of killing
Steam or Diablo IV.

## NVDA add-on

Build output:

    utility/d4planner/dist/d4plannerCapture-0.2.0.nvda-addon

The runtime add-on uses NVDA 2026.2's public `filter_speechSequence` extension
point.

Behavior:

```text
non-D4 / uncertain context -> passthrough
D4 + --speech             -> capture + passthrough
D4 + default silent       -> capture; if persistence succeeds, return []
capture write failure     -> passthrough
```

This fail-safe policy avoids silencing the desktop when source detection or
persistence is uncertain.

## Safety boundary

D4Planner does not:

- read Diablo IV RAM/process memory;
- inject DLL/code into the game;
- copy controller DLLs into the game directory;
- hook DirectX;
- modify game files;
- automate mouse/keyboard/controller gameplay;
- force-kill Diablo IV or Steam by default.

## CI

    python -m pip install -e "utility/d4planner[dev]"
    python -m pytest -q utility/d4planner/tests
    python -m compileall -q utility/d4planner
    python utility/d4planner/tools/build_nvda_addon.py

Acceptance ownership and the detailed Unit / E2E / Real-A / UAT gate matrix are
tracked in #43.
