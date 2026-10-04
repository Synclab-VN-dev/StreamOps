# D4Planner - NVDA capture POC

Issue: #39

This folder is an intentionally independent bounded context for the Diablo IV
Build Tracker experiment. It must not depend on streamops.server or modify the
Diablo IV process/game directory.

## Current scope

Diablo IV -> NVDA accessibility speech -> d4plannerCapture NVDA add-on
-> raw-d4-speech.jsonl -> poc-report.md

No item parser, D4 database, target build integration, OCR, memory reading,
input automation, Web UI, or OBS overlay is part of this POC.

## Build the NVDA add-on

PowerShell:

    python -m pip install -e "utility/d4planner[dev]"
    python utility/d4planner/tools/build_nvda_addon.py

Output:

    utility/d4planner/dist/d4plannerCapture-0.1.0.nvda-addon

Install the generated package through NVDA's Add-on Store / install-from-file
flow, then restart NVDA.

By default the add-on only persists speech while the foreground process/title
looks like Diablo IV.

Capture path:

    %LOCALAPPDATA%\d4planner\raw-d4-speech.jsonl

Optional environment variables:

- D4PLANNER_CAPTURE_PATH: override output JSONL path.
- D4PLANNER_CAPTURE_ALL=1: diagnostic fallback when NVDA cannot reliably
  identify Diablo IV foreground context. This can log speech from other apps;
  use only for the POC and review the output before sharing it.

## Manual Real-A acquisition

Agent F should install and verify the add-on first. The operator then opens
Diablo IV and hovers/focuses representative items:

1. one equipped item;
2. one normal Legendary/Rare item;
3. one Unique;
4. one item with Temper/Masterwork;
5. one Greater Affix item when available;
6. Charm/Seal when available.

The operator is only supplying real game input; evidence processing remains
automated.

## Generate report skeleton

PowerShell:

    python -m d4planner.report.poc_report "%LOCALAPPDATA%\d4planner\raw-d4-speech.jsonl" -o "utility/d4planner/artifacts/d4-nvda-poc/poc-report.md"

The report deliberately leaves gameplay fields as NOT_EVALUATED. Agent F or a
reviewer must inspect raw evidence and conclude GO / PARTIAL / NO-GO.

## CI

    python -m pip install -e "utility/d4planner[dev]"
    python -m pytest -q utility/d4planner/tests
    python -m compileall -q utility/d4planner
    python utility/d4planner/tools/build_nvda_addon.py

## Test ownership

- CI: package/build, JSONL serialization, ordering, context helper, failure
  isolation, report skeleton.
- Agent F on A: install/load NVDA add-on, verify capture path and real JSONL,
  collect artifacts and generate the report.
- Operator manual: open D4 and hover/focus real items to create authoritative
  game accessibility input.

A NO-GO result is still a valid POC outcome when supported by evidence.
