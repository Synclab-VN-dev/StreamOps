# Equipment HUD source and UI acceptance map

Approved S6 review baseline: MagicPath project `458763473602621440`, component
`458765764401446912`, revision `464988421014827008`. This revision replaces
LIVE with the top-right Target menu, hides Charms for Release 1, and retains
Equipment, Compare, Affixes, Effects, score, issues and Pin. Pin means
always-on-top only. **Coverage is not a HUD row, bar or badge.**

S1 records this reference and data contract only. Exported source/hash/Golden
and visual acceptance remain `NOT_RUN` work for S6. Approval of this revision
does not prove that every NO_DATA/error/stale state has an independent Golden.

Display metadata is embedded in each committed HUD snapshot. BE resolves stable
IDs to labels/text; FE does not read a catalog, Target file, capture DB, Maxroll data or
hardcoded sample names.

| UI field | Producer/source | Contract field/type/unit | Status/reason rule |
| --- | --- | --- | --- |
| Target menu label | BE activated Target | `context.target.{targetId,displayName,buildDisplayName}` | Null in no-target/unavailable states; failed attempt does not relabel active Target |
| Target menu options | BE folder listing over managed IPC | `target.list.result.targets[]` | Invalid entries disabled with safe codes; no client paths |
| Build display name | Activated Target metadata | `context.target.buildDisplayName` | Synthetic fixtures explicitly say Synthetic |
| Equipment row | BE committed assessment | `equipment[]`, `slotId`, `slotLabel`, status/reason | Current/Target stay distinct; unknown slot is not empty |
| Current item | Capture/equipment projector | `currentItem.{itemId,displayName,observedAt,source}` or null plus `currentPresence` | Never copied from Target; null is interpreted through presence/evidence |
| Target item | Activated canonical Target + BE display metadata | `targetItem.{itemId,displayName}` | Sample base item name is display context, not matching identity |
| Affix/effect identity | BE assessment service | comparison `kind`, source group/occurrence, `entityId`, `label`, `displayText` | FE never fuzzy-matches or resolves IDs |
| Parameter comparison | BE assessment service | typed `expected`/`actual`, comparator, label, index, unit, evidence/status/reason | Multi-parameter criterion shown without multiplying criterion weight/issues |
| Criterion status | BE assessment service | `PASS/WARN/FAIL/UNKNOWN` + reason code | Text/icon, not color only; UNKNOWN remains distinct |
| Headline score | BE assessment service | status, full-precision value, passed/evaluable weight | NO_DATA shows score `—`; final display uses half-up, no intermediate rounding |
| Issues | BE assessment service | `failIssueCount` | Distinct FAIL criteria only; WARN not counted |
| Issues-only filter | FE filter over BE statuses | comparisons with FAIL or WARN | Filtering only; FE does not recalculate status |
| Equipment x/y | BE assessment service | `itemsPassing/itemsTargeted` | Item passes only when every target criterion PASS |
| Recommendation | BE assessment service | action, display text, reason/criterion IDs | Core FAIL → core WARN → non-core WARN → target order/ID |
| Pin | Native FE shell | approved always-on-top toggle | No implied lock-position or persistence after restart |
| Capture eligibility | Native FE window identity/title | Existing StreamOps `window_capture` source settings | Normal selectable native window; no D4Planner-specific OBS/Steam Link adapter |
| Capture health | Capture pipeline | `health.capture` | Separate from score/Rule Kit health |
| Score freshness | Binding coordinator | `health.scoreFreshness` | CURRENT only while runtime/character/current/target/policy binding matches |
| Rule Kit health | RuleKit wrapper/client | `health.ruleKit` | `NOT_REQUIRED` may accompany a valid Equipment score |
| Audit provenance | BE/capture | top-level producer/assessment version/capture revision/last observed | Enables freshness/review; not fabricated by FE |

`score.evaluationCounts` is internal score-audit/diagnostic metadata. It is
transported for verification but is not a visible Coverage requirement.

The FE may own expand/collapse, selected row, Issues-only filtering and the
always-on-top command. It cannot calculate score/status, read Target/capture DB/catalog,
or replace missing data with MagicPath mock values. Production screenshots
cannot be promoted as independent MagicPath Goldens.

S6/S7 verify the packaged HUD window through the existing StreamOps
`window_capture` flow. This contract does not claim that runtime verification
has run and does not add a capture subsystem.

D5: every displayed HUD field above comes from the validated public SQLite read-model
through the Tauri native reader. React does not open SQLite. Offline preserves valid
last-known data as OFFLINE/STALE, disables BE commands and never implies live capture.
Missing DB/row is NO_DATA; incompatible/corrupt/unreadable DB is a typed error.
