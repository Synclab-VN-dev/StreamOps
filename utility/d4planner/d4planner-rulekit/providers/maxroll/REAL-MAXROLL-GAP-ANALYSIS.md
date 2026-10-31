# Real Maxroll compatibility gap analysis

Scope: updated after implementing the bounded `maxroll-ui-cdp-v1` strategy. No real Maxroll assets
were downloaded, captured or provisioned, and no online Maxroll test was run. Synthetic regression
and deterministic real-protocol unit tests are local PASS; runtime acceptance remains blocked.

| Component | Synthetic implementation | Real Maxroll requirement | Gap | Impact tới user nếu không sửa | Proposed solution / dependency |
|---|---|---|---|---|---|
| Runtime boot | Navigate pinned snapshot, wait for `data-role=ready` | Boot an authorized SPA snapshot and detect planner readiness through version-specific evidence | Real strategy waits for the pinned New Profile UI and resolved CDP breakpoint, but has not run on an authorized package | Session cannot initialize or may read before the planner is ready | Implemented contract; run `test:real` after authorized provisioning |
| Build mapping | Bounded Rogue L50 JSON with one Helm/effect | Map the approved native profile plus every supported input through a permitted UI/import contract | Current mapper is intentionally only the bounded PoC schema | Unsupported fields must fail; silently treating this as full build support would calculate the wrong character | Keep the bounded capability; add mappings incrementally with independent read-back tests and capability updates |
| Item/effect mutation | Fill `data-role=build-json`, click `data-action=apply-build` | Use real Maxroll UI-supported flow and observe recalculation | Real strategy creates an unsaved profile and applies only the bounded Helm/effect; runtime validation is blocked | Preview/commit may return stale A as B | Implemented UI-only strategy + phase capture; run authorized A→B→A gate |
| Metrics extraction | Read synthetic metric nodes | Observe `heroDetails` through CDP and read UI displays independently | Real extractor contract has 50 finite/raw, 34 display and single-use freshness gates; runtime validation is blocked | Stale/incomplete stats could look valid | Implemented fail-closed extractor; validate on authorized runtime |
| Read-back verification | Hash synthetic JSON | Re-enumerate applied class/level/difficulty/item/effect | Real strategy verifies exact bounded state and modifier count; DOM anchors remain unvalidated on the package | Provider could report partial apply as success | Implemented canonical read-back; drift must fail MXP-09 |
| Runtime/version pin | Synthetic DOM identity nodes | Verify manifest, patch, asset and breakpoint | Historical version profile exists; independent snapshot trust anchor is absent | Patch drift could yield wrong calculations | Exact profile implemented; Owner must provision manifest digest/authorization |
| Snapshot offline replay | Generic Snapshot Manager captures local fixture; strict replay has zero origin egress | Authorized snapshot must include the real calculation-critical asset graph, dynamic imports/data/workers, with legal storage approval | No authorized Maxroll snapshot exists in this branch | Real runtime cannot start offline; online fallback would be nondeterministic and outside scope | Owner/authorized process provisions the snapshot; future Real Maxroll Online CI validates acquisition separately, then offline MXP-09 runs here |

## Architectural conclusion

`MaxrollProvider` and `MaxrollSession` now select components through `MaxrollComponentFactory`.
Synthetic DOM and real UI/CDP code are separate strategies, and the historical patch profile pins
the proven asset SHA, breakpoint and UI semantics. The reusable real test still needs an
Owner-authorized snapshot/provenance before it can validate those historical assumptions against a
runtime package. It is not safe to claim MXP-09 from strategy tests alone.

Real status is `REAL_ADAPTER_CONTRACT_PASS / BLOCKED_AUTHORIZED_SNAPSHOT`. Future Real Maxroll
Online CI is owned by the separate ChatGPT room named by the Owner and is intentionally not
implemented here.
