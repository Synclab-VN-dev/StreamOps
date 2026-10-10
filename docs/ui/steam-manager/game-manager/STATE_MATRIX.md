# State, interaction, source-of-truth matrix (#84)

## Never merge these four domains
| Dimension | Allowed states | Meaning |
|---|---|---|
| Game process | RUNNING, STOPPED, STARTING, STOPPING, FAILED, UNKNOWN | Host A observation / operation state; not inferred from Steam |
| Window | FOREGROUND, BACKGROUND, NOT_DETECTED, UNKNOWN | Windows desktop observation; never inferred from process |
| OBS capture | VERIFIED_ACTIVE, CONFIGURED_ONLY, INACTIVE, ERROR, UNKNOWN | Frame verification independent from OBS scene/source configuration |
| Stream selection | SELECTED, NOT_SELECTED, UNKNOWN | Verified selection, only if BE defines canonical source-of-truth |

Show `UNKNOWN`, not `STOPPED`, for disconnected or stale observations. Timeouts require reconciliation. Game STOPPED does not imply Steam STOPPED, and vice versa.

## Fixture walkthroughs (Game Manager dropdown)
| Scenario | Steps in MagicPath | Expected UI |
|---|---|---|
| Default | Select Diablo IV | Running + FOREGROUND, OBS Configured only, stream selection selected |
| Multiple running | Select Multiple running | 3 running games from mixed launchers; independent per-game status |
| No running | Select No running games | Empty running section, game library still available |
| No registrations | Select Empty library | Library empty state |
| Offline | Select Host disconnected | UNKNOWN counts, cannot control games |
| Session mismatch | Select Session mismatch → Detail | Warning / actions disabled |
| Invalid capture | Select OBS black frames → Detail | Game still running, capture ERROR |
| Restart failure | Select Restart failed → selected D4 → Restart + Confirm | STOPPING → FAILED; reconcile before another mutation |
| Start failure | Select Start failed → selected D4 → Start + Confirm | STARTING → FAILED, retry/check message |
| Stop timeout | Select Stop timed out → selected D4 → Stop + Confirm | STOPPING → UNKNOWN, NOT claimed stopped |
| Reconcile | From UNKNOWN press Refresh / reconcile process | Demo refreshed RUNNING, activity entry added; no lifecycle mutation |
| Stale observation | Select Stale data → selected D4 | UNKNOWN and actions disabled until refresh |
| External process exit | Select External game exit | STOPPED without an automatic restart |
| Loading | Select Loading game inventory | Unknown counters / loading placeholder, no control actions |
| Advanced safety | Running game detail → Advanced → Force stop | Warning on save loss; confirm/cancel; demo only |
| Search and filters | Search by game/provider; change All / Running / Stopped | Correct local fixture filter |
| Steam loading / error | Steam preview selector → Loading inventory / Inventory request error | No fictitious 0 running state; UNKNOWN counts and explanatory placeholder |
| Steam without game | Steam preview selector → no games | No games running + library CTA |
| Steam stopped with external game | Steam preview selector → Steam stopped | Running external game remains visible |

## Action state rules
- START: STOPPED or FAILED and session/launcher verified → confirm (if applicable) → STARTING → actual observed RUNNING / FAILED / UNKNOWN.
- STOP: RUNNING → confirmation → STOPPING → observed STOPPED; timeout → UNKNOWN + Refresh / Reconcile.
- RESTART: RUNNING → confirm → graceful STOP, verify, then START; failure must not silently count success. UI prototype compresses internal backend phases, production must expose step progress.
- FORCE STOP: advanced only, explicit unsaved progress warning, permission gate, no default Steam shutdown/restart.
- Pending: disable duplicate mutation, log the request; do not synthesize a verified process state just from HTTP 200.
- Refresh / Reconcile: read-only BE observation with operation id / observedAt; should never run Steam restart implicitly.
- OBS capture: CONFIGURED_ONLY must not show VERIFIED_ACTIVE even when game process is RUNNING.

## Validation boundary
Interaction state was implemented as mock fixture and MagicPath builds passed. Actual remote Android browser smoke, keyboard navigation, visual viewport overflow and physical Game Detail manual approval require device/session evidence, tracked as manual acceptance. No unit/E2E production suite is claimed for these design-only prototypes.
