# #111 — Synthetic offense simulator and real Graph input safety gate

Sandbox-only, **not** game-accurate DPS. Formula Graph stat calculations
remain in #110 and are never duplicated here. The simulation supports
deterministic time events, capped proc chances, crit, ICD/cooldown, resource
usage/regeneration, uptime, skill rank and seeded stochastic convergence.
`require_graph` refuses a real DPS claim when required metrics or live
conditions are UNKNOWN/UNVERIFIED or Graph publishing is not approved.
All results explicitly mark `realDps=null`, `publishAllowed=false`.

The synthetic vectors cover algorithm correctness only; Maxroll Golden,
two-build real Graph→DPS E2E and owner approval are still pending.
