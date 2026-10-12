# Issue #69 — SQLite event store + Steam Input marker capture

## Scope

This issue changes the canonical runtime event history from per-session `events.jsonl`
files to a shared SQLite database at `%LOCALAPPDATA%\d4planner\state\events.db`.
The existing `character.db` remains the materialized/current character state.

The NVDA add-on still writes `raw-speech.jsonl` as its process-to-process ingress.
Equipment diagnostics remain JSONL. JSONL fixtures remain supported for replay/tests.

## Runtime data flow

```text
NVDA add-on
  -> raw-speech.jsonl
                    \
                     -> Supervisor -> ordered EventStore -> events.db (WAL)
Steam Input F11    /                        |
  -> marker queue                           +-> speech.raw -> EquipmentProjector
                                                     -> character.db
```

Only the Supervisor writes canonical events. The marker worker never writes SQLite.

## Event modules

```text
runtime/events/
  model.py       EventDraft / EventEnvelope
  repository.py  SQLite writer + independent CLI reader
  migration.py   idempotent legacy events.jsonl import
  store.py       session sequence allocation + envelope creation
```

## Canonical schema

```sql
CREATE TABLE event_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  timestamp TEXT NOT NULL,
  type TEXT NOT NULL,
  data_json TEXT NOT NULL,
  UNIQUE(session_id, event_seq)
);
```

SQLite uses WAL and NORMAL synchronous mode. Runtime burst ingress is committed as
ordered batches instead of opening/flushing/closing a file for every event.

## Marker schema

`input.marker.raw` is evidence only. It does not mean Equip.

```json
{
  "eventSeq": 5824,
  "type": "input.marker.raw",
  "timestamp": "2026-10-09T03:00:00.200+07:00",
  "sessionId": "...",
  "data": {
    "source": "steamInput",
    "device": "keyboard",
    "key": "F11",
    "virtualKey": 122,
    "state": "down",
    "process": "diablo iv",
    "processId": 1280,
    "contextSource": "win32Foreground",
    "windowTitle": "Diablo IV"
  }
}
```

The capture worker only queues an edge when the foreground PID matches the active
Diablo IV PID. It is fail-open and independent of speech capture.

## Legacy migration

Existing `sessions/*/events.jsonl` files are imported idempotently. The unique
`(session_id,event_seq)` key prevents duplicates. Migration metadata tracks file
size/mtime so unchanged sources are skipped. Malformed lines are skipped without
aborting the rest of the file. Legacy files are never deleted automatically.

## CLI

Normal `d4planner logs` reads SQLite. `--raw`, `-f`, and `--from-end` keep
their existing behavior. `--component equipment` continues to read the
equipment diagnostic JSONL.

## Out of scope

No ActionEvidenceProvider, EquipTransitionResolver, or equipment mutation based
on F11 is implemented in #69.
