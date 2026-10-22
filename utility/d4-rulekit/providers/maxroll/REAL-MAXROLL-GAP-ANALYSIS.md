# Real Maxroll compatibility gap analysis

Scope: static architecture/source review only. No real Maxroll assets were downloaded, captured or
provisioned, and no online Maxroll test was run. The current implementation is Phase A infrastructure
validated against a Maxroll-shaped synthetic runtime.

| Component | Synthetic implementation | Real Maxroll requirement | Gap | Impact tới user nếu không sửa | Proposed solution / dependency |
|---|---|---|---|---|---|
| Runtime boot | Navigate pinned snapshot, wait for `data-role=ready` | Boot an authorized, complete SPA snapshot and detect planner readiness through version-specific evidence | Synthetic readiness selector does not exist on the real planner | Session cannot initialize or may read before the planner is ready | Add a versioned real runtime strategy after an authorized snapshot is provisioned; prove readiness and dynamic imports/workers offline |
| Build mapping | Bounded Rogue L50 JSON with one Helm/effect | Map the approved native profile plus every supported input through a permitted UI/import contract | Current mapper is intentionally only the bounded PoC schema | Unsupported fields must fail; silently treating this as full build support would calculate the wrong character | Keep the bounded capability; add mappings incrementally with independent read-back tests and capability updates |
| Item/effect mutation | Fill `data-role=build-json`, click `data-action=apply-build` | Use real Maxroll UI-supported edit/import flow and wait for its actual recalculation lifecycle | Synthetic textarea/button protocol is not present in real Maxroll | Preview/commit cannot change the real runtime, or may return stale A as B | Implement a version-specific `RuntimeAdapter` strategy using the already approved UI flow; do not write React/internal state directly |
| Metrics extraction | Read `data-metric-id` nodes with raw JSON attributes | Observe `heroDetails` values through the proven CDP/React render closure and independently read available UI display values | Real raw metrics are not exposed through the synthetic DOM contract | 50/50 raw and 34/50 display synthetic coverage does not imply real coverage | Add a real extractor strategy using authorized CDP observation, phase/freshness markers and the same finite-number/catalog gates |
| Read-back verification | Hash JSON rendered into `data-role=applied-build` | Re-enumerate the real applied item/effect/build state from supported UI/runtime evidence | No real canonical read-back mapping exists | Provider could report success when Maxroll rejected or partially applied a change | Define per-input real read-back anchors and canonicalization; reject partial/ambiguous state before extracting metrics |
| Runtime/version pin | Synthetic DOM nodes contain runtime, patch and asset SHA | Verify approved snapshot manifest, observed game patch and actual runtime asset fingerprints | DOM identity fields are fixture-only; current asset check proves snapshot integrity, not real semantic identity | Patch drift could yield incompatible selectors or wrong calculations | Provision external trust anchors and a version profile from authorized evidence; require exact match and fail closed |
| Snapshot offline replay | Generic Snapshot Manager captures local fixture; strict replay has zero origin egress | Authorized snapshot must include the real calculation-critical asset graph, dynamic imports/data/workers, with legal storage approval | No authorized Maxroll snapshot exists in this branch | Real runtime cannot start offline; online fallback would be nondeterministic and outside scope | Owner/authorized process provisions the snapshot; future Real Maxroll Online CI validates acquisition separately, then offline MXP-09 runs here |

## Architectural conclusion

`MaxrollProvider` and `MaxrollSession` boundaries are reusable, but the current
`MaxrollRuntimeAdapter`, `MaxrollBuildMapper`, `MaxrollMetricsExtractor` and selector portion of
`MaxrollPatchProfile` are synthetic-version implementations, not a real Maxroll adapter. A real
profile should select injected strategy implementations rather than add real selectors/React logic
to Application or Browser Infrastructure. This requires Owner-authorized snapshot/provenance and a
separate bounded implementation/review; it is not safe to claim that snapshot provisioning alone
will make MXP-09 pass.

Real status remains `BLOCKED_AUTHORIZED_SNAPSHOT_AND_REAL_ADAPTER`. Future Real Maxroll Online CI is
owned by the separate ChatGPT room named by the Owner and is intentionally not implemented here.
