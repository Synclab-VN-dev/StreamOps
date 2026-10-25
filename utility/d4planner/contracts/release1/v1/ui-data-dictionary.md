# Equipment HUD source and UI acceptance map

Baseline is MagicPath project `458763473602621440`, component
`458765764401446912`, revision `458808549301174272`, handed off on the separate
`docs/ui-design` branch at `docs/ui/d4-planner/build-overlay`. It approves the
Equipment concept/layout, not runtime fixtures or an API contract. Target
selector, Equipment-only navigation, coverage, partial/NO_DATA, stale/error and
health separation are a minimal S6 delta requiring a new Owner-pinned reference.

| UI field | Producer/source | Contract field/type/unit | Status/reason rule |
| --- | --- | --- | --- |
| Selected Target | BE TargetRepository activated record | `selectedTarget.{targetId,displayName,contentSha256}` strings | Never display a listed-but-not-activated file as selected |
| Target selector options | BE folder listing over WS | `target.list.result.targets[]` | Invalid entries disabled with safe `errorCodes`; FE never receives/opens paths |
| Equipment row | BE assessment committed model | `equipment[]`, stable `slotId`, status enum | Current and Target identities remain distinct; unknown slot is not empty |
| Current item | Capture/equipment projector evidence | `currentItemId`, `currentPresence` | `UNKNOWN` unless observed or confirmed absent; never copied from Target |
| Target item | Activated canonical target | `targetItemId` | Display context only; matching does not require sample item name |
| Affix/effect pair | BE assessment service | comparison identity, comparator, typed values and unit | FE formats only; no fuzzy identity or numeric scoring in FE |
| Criterion status | BE assessment service | `PASS/WARN/FAIL/UNKNOWN` + `reasonCode` | Must have text/icon, not color only; UNKNOWN stays distinct |
| Headline score | BE assessment service | `score.status`, `value` (0..100 or null) | `NO_DATA` renders no numeric score; FE never recomputes |
| Score numerator/denominator | BE assessment service | `passedWeight`, `evaluableWeight` | Optional presentation, mandatory model; UNKNOWN excluded |
| Coverage | BE assessment service | criteria count ratio | Separate label from score and x/y; null ratio only when denominator zero |
| Issues | BE assessment service | `failIssueCount` count | Unique FAIL criterion count; WARN excluded |
| Warnings | BE assessment service | `warnCount` count | Separate from issues; issues-only filter behavior awaits D2 |
| Equipment x/y | BE assessment service | `itemsPassing/itemsTargeted` items | Not capture coverage; aggregation awaits D2 approval |
| Recommendation | BE assessment service | action + reason/criterion IDs | Current-vs-Target only; no inventory/stash suggestion |
| Capture health | Capture pipeline | `health.capture` | Describes evidence producer, not score/worker health |
| Score freshness | Binding/revision coordinator | `health.scoreFreshness` | CURRENT only when all binding keys still match |
| Rule Kit health | RuleKitProcessWrapper/client | `health.ruleKit` | Independent; `NOT_REQUIRED` may accompany valid Equipment score |
| LIVE badge replacement | BE binding/health model | three health fields + revisions | Do not collapse the three meanings into one green LIVE badge |

All visible data is from the committed HUD snapshot over WS. Local UI state may
control expand/collapse, row selection and filtering only. It cannot calculate
scores, read the Target folder/DB, or replace missing data with MagicPath mock
values. Production screenshots cannot be promoted as design Goldens.
