# Maxroll multi-class fixture capture

## Status

The owner-approved 2026-10-24 capture covers all eight classes with at least one independently
attested build. Seven new inputs came from anonymous, read-only Maxroll planner sessions; the
existing Rogue Endgame pair was integrity-checked and reused. Plaintext inputs and outputs remain
under a private, Git-ignored local root.

All offline replays use snapshot `maxroll-20261023T034150Z`, manifest SHA-256
`638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54`, and calculation asset
SHA-256 `891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db`.

| Class | Maxroll source | Profile read-back | Raw | Display |
|---|---|---:|---:|---:|
| Rogue | <https://maxroll.gg/d4/planner/1g1any0x#3> | Endgame | 50 | 50 |
| Sorcerer | <https://maxroll.gg/d4/planner/j849ij0q> | Endgame | 50 | 51 |
| Druid | <https://maxroll.gg/d4/planner/6p33iv0e#2> | Endgame | 47 | 47 |
| Barbarian | <https://maxroll.gg/d4/planner/134cn80q#3> | Endgame | 47 | 49 |
| Necromancer | <https://maxroll.gg/d4/planner/xf9um40q#3> | Endgame | 49 | 49 |
| Spiritborn | <https://maxroll.gg/d4/planner/5zxmig0x#3> | Endgame | 50 | 57 |
| Paladin | <https://maxroll.gg/d4/planner/m9369d0t#4> | Push | 46 | 46 |
| Warlock | <https://maxroll.gg/d4/planner/to4erl0e#3> | Endgame | 44 | 44 |

The denominator is runtime-observed per class. It is intentionally not forced to Rogue's 50 IDs.
Every vector is finite, unique within one calculation epoch, exact between online source and
offline replay, and accompanied by all display rows actually rendered.

## Command

```bash
npm --prefix utility/d4-rulekit/providers/maxroll run fixtures:capture-classes -- \
  --output /private/maxroll-fixtures/run-id \
  --reuse-root /private/maxroll-fixtures/issue-134-gb-e1-att-v2 \
  --snapshot-root /approved/maxroll-snapshots \
  --snapshot-id maxroll-20261023T034150Z \
  --manifest-sha256 638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54 \
  --chromium /path/to/chromium
```

`fixture-sources.json` is the reviewable source matrix. The command refuses output overwrite,
wrong class/level, runtime hash drift, incomplete or mixed-epoch metrics, source/replay mismatch,
offline egress, invalid reused evidence, and cleanup failure. It writes immutable input/output
pairs, `fixture-matrix.json`, and `manifest.sha256` only to the requested private directory.

This evidence resolves the independent-class-fixture gap. It does not resolve the separate
catalog relationship gaps documented in `UNIVERSAL-IMPORT-COVERAGE.json`, and it does not by
itself prove every valid build combination.
