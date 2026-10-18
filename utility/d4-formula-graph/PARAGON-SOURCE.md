# DEV-00 independent Paragon contributor source (Issue #110 / M20)

Read-only F3 capture source from `Synclab-VN-dev/synclab-agent@bb4c5cc6b2135583eb708f0a3f374060675b6c0b`,
`evidence/StreamOps-106/F3-rogue-50/rogue-50-input-snapshot.json`, Git blob `4d14854e0f0abfe234b2e58e270f47db1472b4ff`.

`primary_paragon_source.py` consumes the 270 captured active UI Paragon
tooltips (the source text is **not** Maxroll Golden Expected). It reports
per-node attribute lines and their observational subtotal, with a determinism
hash. It does not claim that UI glyph/rare/gate semantics form a complete
additive stat equation. Missing base/level, Altars, equipment NID mappings,
socket/charm effects, and stacking keep all four primary stat ACTUALs null.

Run:

```sh
python utility/d4-formula-graph/primary_paragon_source.py \
  --source utility/d4-formula-graph/fixtures/dev00-paragon-tooltip-source.json \
  --report artifacts/110-paragon-source-components.json
python -m unittest discover -s utility/d4-formula-graph/tests -p 'test_primary_paragon_source.py' -v
```

This **does not** change public DSL v1, Golden policy, rule promotion, production
outputs, existing Level VERIFICATION, or Epic acceptance. It is a causal-contributor
research increment that makes the next source gaps concrete. No Golden values
are stored or read in this calculation.
