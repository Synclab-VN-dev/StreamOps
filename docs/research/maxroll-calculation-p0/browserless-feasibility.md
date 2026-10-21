# Maxroll Browserless Engine Feasibility — Checkpoint 1

## Executive conclusion

**Recommendation: NO-GO for browserless extraction with current evidence.**
No supported function accepting build state and returning Character Stats has been identified.
The verified path obtains values from a React render closure through a CDP paused call frame.
Pure Node or a DOM shim would therefore require substantial, version-fragile runtime reconstruction.
Keep a persistent Chromium worker as the production-oriented fallback; reconsider only with a supported engine boundary from Maxroll.

## Scope and assumptions

- Baseline: `8515072bbb18c27eae531c878272556e77f00`, patch `3.2.1.73552`.
- Evidence reviewed: dependency inventory, L3/dependency report sections, browser adapter, and Python runner.
- No browser run, bundle download, deep minified-code review, deobfuscation, or implementation was performed.
- Estimates are planning ranges for one engineer/agent familiar with the existing PoC, not measured delivery commitments.
- Token estimates mean expected Dev F model-token allocation for implementation/review iterations; they are not actual usage.

## Dependency summary

| Dependency | Classification | Current evidence / implication |
|---|---|---|
| Formula/evaluation logic (`heroDetails`, observed evaluation path) | Pure JavaScript likely exists internally, boundary unresolved | Execution is proven, but no callable public/exported engine interface is identified |
| Game data and lookup tables | Required | `data.min.json` is in the working runtime; exact calculation-only subset is not minimized |
| Locale/item identity data | UI adapter required; calculation requirement unknown | Current UI-driven input mapping uses it |
| In-memory build state | Required | A/B mutation causally changes all captured results as expected |
| React state/render closure | Required by verified capture path | Raw values are read as closure variables via `Debugger.evaluateOnCallFrame` |
| DOM and event system | Required by verified input path | Current adapter creates the profile and applies items/modifiers through UI events |
| Planner document/module graph | Required by current runtime | Working package contains 354 entries/~59 MB; calculation-only graph is unknown |
| Dynamic imports | Present, boundaries unknown | The proven archive contains the loaded module graph, not a minimized dependency DAG |
| Web Workers / WASM | Not observed | Absence is not proven; neither is a known blocker today |
| Remote calculation service | Not required | Offline A/B/A succeeds with zero remote calculation responses |

## Direct dependency assessment

1. **Independent build → stats function:** not found. Evidence shows evaluation occurring inside the planner, not an exported function contract.
2. **Coupling location:** profile/item state is created through React/UI state; metric values are exposed during render in the `heroDetails` closure; capture requires CDP pause/evaluation.
3. **Likely Node requirement:** more than a small adapter. Pure Node needs module initialization, build-state construction, calculation context, lookup data, and metric enumeration reconstructed. A shim additionally needs enough DOM/React scheduling behavior to reach the same render closure.
4. **Unknowns:** actual formula entry point and signature, initialization order, hidden globals/singletons, dynamic-import minimum set, side effects, browser-global usage, and whether `evalFormulaNumber` can be invoked with a complete standalone context.

The stop condition is met: resolving these unknowns requires targeted analysis of proprietary minified runtime or a supported interface/source mapping not present in current evidence.

## Option comparison

| Option | Feasibility | Initial effort | Dev F token estimate | Per-patch maintenance | Risk | Expected performance benefit | Main blocker |
|---|---|---:|---:|---:|---|---|---|
| A. Pure Node.js | LOW | 120–240 person-hours | 300k–800k | 24–80 hours | VERY HIGH | UNKNOWN; potentially high, unmeasured | No exported engine; must reconstruct state/context/module initialization |
| B. Node.js + lightweight DOM/browser shim | LOW | 80–160 person-hours | 200k–500k | 16–48 hours | HIGH | UNKNOWN; shim/React overhead may erase benefit | “Lightweight” shim may grow into partial browser/React runtime |
| C. Persistent Chromium worker | HIGH; already proven bounded | 16–40 hours to harden | 40k–100k | 4–16 hours | MEDIUM | Cold start can be amortized; throughput gain unmeasured | Patch-specific selectors, breakpoint location, runtime-package lifecycle |

## Initial versus recurring effort

### A — Pure Node

- Initial: identify a stable calculation boundary, reproduce initialization/context, map build JSON directly, enumerate 50 metrics, and establish A/B/A parity.
- Recurring: re-identify minified symbols/module boundaries and revalidate every supported input group after each Maxroll patch.
- A single renamed closure or changed bundler graph can invalidate the adapter without a compile-time signal.

### B — Node plus shim

- Initial: all engine-boundary work from A plus DOM globals, events, scheduling, module loading, and possibly React rendering/state ownership.
- Recurring: maintain compatibility with both Maxroll runtime changes and shim behavior.
- If React must actually mount to expose `heroDetails`, this ceases to be a lightweight calculation engine and approaches a less compatible browser reimplementation.

### C — Persistent Chromium

- Initial hardening: long-lived worker lifecycle, isolation/reset, queueing, health checks, patch fingerprinting, resource limits, and stale-state tests.
- Recurring: update runtime package and selectors/breakpoint, then run existing A/B/A and 50-metric parity gates.
- Existing measurements are about 7.5 seconds cold local load and 1.37 seconds per bounded calculation; persistent-worker throughput has not yet been measured.

## Recommendation

**NO-GO** for implementing A or B now. Their cost and maintenance risk are not justified while C already provides exact 50/50 online/local parity and fail-closed offline operation.

Use C as the reference provider architecture. Prefer a small pool of persistent, disposable Chromium workers over a browserless fork. Preserve process isolation and periodically recycle workers to prevent state leakage.

Reopen browserless work only if Maxroll supplies at least one of:

- a documented/exported calculation API or module function;
- a supported engine package with build/context schemas;
- source maps or authoritative entry-point guidance sufficient to avoid reverse-engineering React internals.

## Optional prerequisite spike — not authorized in this checkpoint

If the supported entry-point prerequisite becomes available, a bounded 8–16 hour spike may test one metric set only.

Acceptance would require: one direct Node call from Build A and B, 50/50 raw metric enumeration, exact A/B/A parity, no DOM/React mount, no Chromium/CDP, deterministic repeatability, and a documented dependency/version contract. Failure of any condition returns to option C; it must not expand into open-ended bundle reconstruction.

## Next WHAT / WHO / WHY / HOW

| WHAT | WHO | WHY | HOW |
|---|---|---|---|
| Continue with persistent Chromium provider | StreamOps implementation owner | Proven correctness and lowest delivery risk | Add worker pooling, reset verification, health checks, metrics, and patch fingerprint gates |
| Request supported engine boundary | Owner + Maxroll | Changes browserless feasibility more than further black-box research | Ask for exported API/package, input-context schema, version policy, and permitted runtime distribution |
| Define performance target before extraction | Product/architecture owner | Browserless benefit is currently hypothetical | Set latency, throughput, memory, concurrency, and maintenance-budget thresholds |
| Run optional bounded spike only after prerequisite | Dev F | Prevent open-ended reverse engineering | Cap at 8–16 hours; apply the acceptance criteria above; do not implement production code |

Checkpoint 1 stops here. No P3 technical spike is started.
