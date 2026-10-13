# FE handoff — component structure, data boundary and delivery gates

## Canonical design

- MagicPath project `458763473602621440`, component `458765764401446912`, selected revision `458808549301174272`.
- Keep **one** design reference for the screen: `D4PlannerCompactBuildHUD.tsx` (and exact copy under `reference/src/components/generated` solely for original scaffold resolution). No edits to reference TSX until Owner explicitly changes MagicPath revision.
- Current React mock is **one component** with local `useState` and fixture data. Suggested production modules (not a change to approved design): `BuildSummary`, `SectionDetails`, `ItemComparison`, `AffixComparison`, `EffectComparison`, `Recommendation`.

## State mapping / controller

| Design state | Mock source | Production expectation / dependency |
| --- | --- | --- |
| Summary expanded/collapsed | `expanded` | Local UI state, no backend mutation |
| Selected Equipment/Charms | `selected` | Local UI state; runtime snapshot selector requires contract |
| Item detail | `item` | Must use real item identity, not name-only demo key |
| Affixes and Effects | `affixOpen`, `effectOpen` | UI toggles; comparisons supplied by future target-vs-current engine |
| Issues only vs All | `showAll` | User-visible filter; preserve UNKNOWN |
| Pin overlay | `pinned` | Mock label only; Tauri OS behavior needs explicit contract and UAT |
| Headline, scores, severity, recommendation | hardcoded fixtures | Future scoring/target build contract; do **not** infer from current equipment alone |

## Data/API dependencies (not finalized in #66)

1. **Current equipment:** D4Planner NVDA/supervisor + equipment projector (#43/#59), read through established D4Planner runtime/CLI; no FE contract or WS event shape is approved here.
2. **Target build:** Charge Bolt JSON/schema, item/affix/effect expectations, rule priorities. Separate BE contract is needed; example values here are *not* rules.
3. **Build scoring/diff:** service should return `PASS | WARN | FAIL | UNKNOWN`, reasons, priority and action hints. Missing/partial evidence stays UNKNOWN, not FAIL. Type mismatch precedes value comparison.
4. **Transport/realtime:** define immutable snapshot version/timestamp, stale/reconnect handling, event sequencing and authorization before connecting real runtime. No fake `LIVE` if backend unavailable.
5. **Windows overlay:** #71 feasibility POC; owner physical acceptance #76, plus OBS/Steam Link interaction require independent verification. Tauri hotkeys and click-through are **not represented by MagicPath TSX**.

## Implementation safeguards

- Native MagicPath export includes mock data and Tailwind styles; **not** a ready-to-run production StreamOps page.
- Maintain layout 248px + 252px + 330px side-by-side and light translucent theme until Owner-approved revision changes.
- Keep reference independent of production code. Do not derive Golden from production screenshots or loosen thresholds for convenience.
- FE ticket must split CI/unit/E2E, Visual Golden Gate, Dev F Real-A, Owner manual. UI state / viewport lacking approved reference = BLOCKED, not green by omission.
- Design-only branch `docs/ui-design` remains separate from master. A production FE branch should consume approved handoff without merging design-only history into master.

## Known unanswered questions

- Concrete responsive behavior when host overlay window is narrower than the three panels.
- Whether summary `LIVE` means capture up-to-date, game process alive, or score availability. Needs backend semantics.
- Error/loading/stale state visuals and per-slot current/target mappings.
- Placement relative to game screen, safe drag/click-through/opacity persistence, OBS and Steam Link visibility.

These questions are **implementation dependencies**; do not change MagicPath implicitly. Request Owner approval only if solving them changes actual visual/contract scope.
