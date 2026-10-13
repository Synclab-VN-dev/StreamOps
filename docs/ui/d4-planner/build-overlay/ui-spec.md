# UI specification — pinned MagicPath revision

**Source:** Project `458763473602621440` · component `458765764401446912` · revision `458808549301174272`. Exact source: `D4PlannerCompactBuildHUD.tsx`.

## Layout

| Surface | Approved output |
| --- | --- |
| Main overlay | Transparent parent `<main>`, `min-h-[550px]`, padding 16px; horizontal flex, gap 12px, width as needed |
| Summary | 248px, `rounded-[20px]`, light `#f3f3f4` at 95% opacity, border white/50, blur and subtle shadow |
| Section details | Additional 252px panel on **right** of summary, separate close control; supports Equipment or Charms |
| Item compare | Additional 330px panel on **right** of section panel; Current vs Target, Affixes, Effects, recommendation |
| Header | Lightning icon, CHARGE BOLT, LIVE, score 78/100 and warning count (fixture values) |
| Semantic statuses | PASS green/check; FAIL red/cross; WARN amber/triangle; UNKNOWN gray/question; never color-only or UNKNOWN=FAIL |

### Visual notes

- **Theme is light translucent**, not the historic dark overlay. Text is dark charcoal (`#252a31`) with muted grayscale metadata. Rounded panels use softened shadows, pale dividers and restrained accent colors.
- Summary header and item list use compact Lucide icons. Typography from MagicPath source (roughly 9–15px labels, 29px headline score). Treat actual source classes as exact expected values; prose is only explanatory.
- On expansion the panels are **side-by-side**, not replaced in place, not full-screen popups. Width may reach 248+12+252+12+330 = 854px before parent padding, so overlay runtime placement must be evaluated later without altering Golden.
- `main` uses `w-full` and `max-w-full` on flex container. **No separate approved mobile/tablet responsive design** or controlled viewport snapshots exist in the current export; do not invent behavior for small host windows.

## Approved interactions

1. First render: expanded summary, score and two rows Equipment 8/10 and Charms 6/8 (fixture).
2. Click summary header: collapse to compact summary while still showing `NEXT UPGRADE` / Gloves; closes details and resets filters; click again expands.
3. Click Equipment or Charms: open matching 252px panel; click same row again closes; switching sections resets selected item and compare expansion.
4. Click a row inside section: open 330px item panel. Clicking close on item only closes that panel. Clicking close on section closes both.
5. Affixes and Effects independently expand/collapse. Affixes default to Issues only, with All filter and Current ↔ Target pairs. Wrong attribute *type* must not be assessed by comparing numeric value.
6. Pin overlay toggles between `Pin overlay` / `Pinned` **only in React memory**. Actual OS pin/persistence is not in this design.

## Data examples from approved mock (not API contract)

| UI area | Examples |
| --- | --- |
| Overview | CHARGE BOLT; 78/100; 3 issues; LIVE |
| Equipment | Gloves FAIL / Wrong core effect; Ring WARN / Crit Chance low; Amulet WARN / Weak affixes; Head PASS |
| Charms | slot 1 PASS; slot 2 WARN / Missing synergy; slot 3 PASS; Other effects UNKNOWN / Not verified |
| Affixes | Attack Speed +9.4% vs ≥8% PASS; Crit Damage +42% vs target Crit Chance ≥8% FAIL/type mismatch; Core Skills +1 vs +2 WARN |
| Effects | Current Overwhelming Currents; target Required Charge Bolt core effect; mismatch |
| Recommendation | KEEP ITEM · CHANGE EFFECT |

**Demo limitation:** the current component renders identical affix/effect comparison content for *any* selected item; no item-aware runtime comparison is implemented here. FE must rely on future contract/fixtures, never treat this demo binding as valid scoring logic.

## Not Golden-approved in this revision

- Legacy #66: summary 340–380px with full priority list, dark theme, inline-replace detail; superseded by this MagicPath revision.
- Idle auto-collapse, click-outside-to-close, dragging, global shortcuts, click-through, OBS visibility, Steam Link behavior, persistent pin; need runtime/Owner review.
- Loading, stale, missing target, partial capture, error/offline, healthy-build alternatives and stat/skill/paragon drilldowns: not depicted as approved render states. Track as gaps, not implicit completed screens.
