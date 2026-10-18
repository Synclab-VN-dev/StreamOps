# #105 M20 Working-model-first delivery (Draft #110 / PR #121)

## Intent
Source-completeness is NOT a prerequisite for calculating a candidate. The
new working model extracts known contributors now, reports explicit coverage
gaps, and allows small, independent contributor handlers to be plugged in
later. Golden Expected never enters the evaluator. Unknown is never silently
defaulted to zero or misrepresented as a final Character Stat.

## SOLID and extensibility (like #119)
The stable processing Template Method:
validate source -> registered ContributorStrategy handlers -> group contributors
by metric ID -> source-bounded F3 arithmetic -> candidate, trace and coverage
-> independent development Golden comparison.

Each ContributorStrategy.produce(source,paragon,rolls) returns an immutable
tuple of SourceContribution(metric_id,family,value,source_id,provenance).
A new case C can add a provider for an observed item NID, class-base, skill
effect, or glyph without editing A/B handlers or the aggregator. ModelRegistry
rejects bad types, duplicate family/source, and missing provenance.
Contracts: SRP pure source-specific providers, OCP registry extension,
LSP stable immutable strategy results, ISP small protocol, DIP no Golden/IO
or DB dependencies in the resolver.

## Real DEV-00 results and remaining uncertainty
Captured 270 active Paragon nodes with 209 literal flat attribute lines:
Strength 339; Intelligence 413; Willpower 75; Dexterity 569.
These are numeric partial source subtotals from real observations; they are
not complete character stats. Any unknown class base/level, item NID mapping,
socket/charm/skill, Altars and glyph stacking remain visible in coverage.
The input roll witness is indexed, but is not assigned fake NID semantics.
Working-model numeric candidates: 5/20 (Level + these four provisional
subtotals). 15 stat candidates remain null until ANY trustworthy contributor
exists. Any sample match on incomplete input is not VERIFIED.

## Independent Golden separation
DEV-00 development Golden original captured 50 rows is byte-exact stored in
fixtures/golden-dev/dev00-original-50.json. Its Git blob is
6220f636f66c9d113c0b41f13480d09d7bed4dc0 from
Synclab-VN-dev/synclab-agent@bb4c5cc6b2135583eb708f0a3f374060675b6c0b.
It is explicitly the DEVELOPMENT capture, NOT sealed HOLDOUT. This file is
loaded only AFTER model candidate generation by a different CLI/module.
The comparator checks original Git blob, patch, class, fingerprint and metrics,
and returns numeric Actual-candidate minus Expected diff for each of 20 IDs.
It never marks provisional candidates as VERIFIED. The only VERIFIED metric
still comes from the existing independent scoped Level Gate.

CI emits:
- artifacts/d4-formula-graph/dev00-working-model-actual-candidates.json
- artifacts/d4-formula-graph/dev00-working-model-vs-golden-20.json

NEXT (ChatGPT+CI): incrementally implement source-backed equipment/skill/
class-base/glyph contributors and actual F3 formulas. Add a regression for
each new case without altering previous PASS cases; run original Golden Gate
before any scoped VERIFIED promotion. No A runtime operations, merge, release
or deployment authorized.
