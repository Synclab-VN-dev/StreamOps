# Rule DSL versioning and patch compatibility — CANDIDATE

- `schemaVersion` identifies the DSL *language* (`1.0.0` candidate). Changing operator
  semantics or weakening validation requires Owner design approval and a schema migration.
- `game.gameVersion` and optional `game.buildNumber` pin **game mechanics data** to a
  Blizzard patch. An AI Agent updates **rule documents**, not schema or engine code, for a
  patch consisting only of data changes.
- Rules carry stable `ruleId`, source `kind` + `gameId`, evidence, `verification.status`
  and confidence. Synthetic fixture IDs use `example.*` and must never be promoted.
- Patch registry (issue #109) must prevent stale rules from matching other patches without
  explicitly declared compatibility. Deprecations/removals must be traceable and reversible.
- `schema_valid` status is **not** proof of semantics. Promotion to `verified` requires
  separate independent reference and G2/G3 review (issue #108).
- Before publish, validate duplicate IDs, missing catalog refs, unsupported operators and
  circular dependencies under G2; **these checks are not implemented in #107**.
- Unsupported mechanic or unknown coefficients remain UNKNOWN/UNVERIFIED, never default zero.
- Major engine/schema extension (new operator, event identity or semantics) is blocked pending
  Owner approval; merely new patch rolls/values normally change rule data only.
