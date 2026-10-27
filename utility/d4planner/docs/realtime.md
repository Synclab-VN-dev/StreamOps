
## Snapshot ownership / readiness (Owner approved 27/10/2026)

`ProductionBackendRuntime.snapshot_management()` forwards the separate Rule Kit
Snapshot Management API. The private managed control channel accepts
`type=rulekit.snapshot`, method and params; this is not an arbitrary-path WS API.
FE only receives normalized Rule Kit health through the existing HUD payload.
Registry, profile/strategy resolution, import validation, activation/rollback and
trust/revocation live exclusively in Rule Kit/S3.

Application/WS/Equipment availability is independent from Maxroll calculation.
No selected snapshot reports Rule Kit UNAVAILABLE, never fabricated READY.
Configured-invalid remains unavailable with diagnostics; Rule Kit upgrade preflight
rejects an incompatible active binding so installer retains old application/data.
Production trust remains blocked until Owner provides the pinned verification key.

`RuntimeHudStore` attaches Rule Kit-owned health and enclosing Backend generation
before the durable commit. Health transitions publish after commit; no rescoring,
Target policy, capture repository access or score-freshness change is implied by
snapshot switch. Equipment remains usable without full character stats/snapshot.
Eight Application APIs and canonical schema are unchanged. Snapshot protocol is
`d4-rulekit-snapshots/v1`, owned/documented in S3.
