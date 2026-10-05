# Issue #35 — Gate 3 technical decision

Status: **PENDING REAL-A EVIDENCE**

Do not convert this file into a production decision from source inspection alone.

## Evidence required

- P1 native output enumeration and per-target control result.
- Native identity before/after OBS restart.
- Upstream Vendor discovery.
- Candidate Vendor capability matrix.
- Candidate ID persistence before/after OBS restart.
- Per-target control and all-target control.
- State/stats behavior.
- Credential redaction result.
- Candidate cleanup.
- Upstream binary/config restore and Gate 1 LOADED verification.

## Capability matrix

| Capability | Native OBS + upstream | Upstream Vendor | Candidate Vendor |
| --- | --- | --- | --- |
| list | PENDING | PENDING | PENDING |
| stable target identity | PENDING | PENDING | PENDING |
| start one | PENDING | PENDING | PENDING |
| stop one | PENDING | PENDING | PENDING |
| start all | PENDING | PENDING | PENDING |
| stop all | PENDING | PENDING | PENDING |
| add | PENDING | PENDING | PENDING |
| update | PENDING | PENDING | PENDING |
| delete | PENDING | PENDING | PENDING |
| LIVE/FAILED state | PENDING | PENDING | PENDING |
| stats/error | PENDING | PENDING | PENDING |
| credential update | PENDING | PENDING | PENDING |
| secret-safe response | PENDING | PENDING | PENDING |

## Decision

**PENDING.**

Allowed final outcomes:

1. Native OBS/upstream is sufficient.
2. Vendor API candidate is suitable for further development.
3. StreamOps must maintain an additional patch under util/.
4. BLOCKED: no sufficiently safe production contract yet.

No production streamops/server/ or UI implementation is authorized by this document.
