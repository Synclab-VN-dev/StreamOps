# Component tree / responsive contract

```text
StreamOps Dashboard (/)
└── Steam Manager (/steam)
    ├── Header / node- and Steam-status pill
    ├── Steam Process Status         existing behavior preserved
    │   └── PID / uptime / session + Restart in Big Picture (demo)
    ├── Game Manager                NEW compact summary
    │   ├── Running and Registered counts
    │   ├── 0 / 1 / 3 / many running rows
    │   └── Manage Games → /games
    └── Activity Log                session-local

Game Manager (/games)
├── Header + mock scenario selector
├── Games overview                 running / registered / capture verified
├── Running games                  interactive cards
├── Game library                   text search, All / Running / Stopped
├── Activity log                   session-local
└── Game Detail                    selected within page, no third route
    ├── Process & Windows session
    ├── Independent window / OBS / stream-selection state
    ├── Start / Stop / Restart + Refresh / Reconcile
    ├── Related services           launcher / OBS / optional D4Planner
    ├── Advanced + Force Stop
    └── Recent activity
```

## Responsive
- Steam uses OBS Plugin Manager mobile-first `max-w-md`; sections remain stacked, summary card collapsed by default except the running-games summary.
- Games uses `max-w-[860px]` ordinarily; desktop opens details in an `lg` right column with `max-w-5xl`.
- Mobile details replace the library viewport with a full-width scrollable detail overlay and an obvious Back/Close action. Do not place a 360px desktop drawer on Android.
- UI uses standard Tailwind responsive breakpoints and `min-w-0`/`truncate` on list rows. Source inspection and preview do not substitute for 360px, 390px and 768px interactive tests on physical device.

## Visual primitives reused
`Pill` emerald / amber / red / neutral / blue; `Stat` small gray label + bold data; `Card` white rounded-3xl expandable card; `GameIcon` Lucide `Gamepad2`; `DetailRow` single status dimension; centered black action button and gray secondary button. No emoji used for iconography.
