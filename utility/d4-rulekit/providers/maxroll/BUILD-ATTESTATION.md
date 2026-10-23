# Maxroll build/output attestation (GB-E1-ATT)

`build:attest` creates a private reference observation that links a native build
export to the calculation engine actually executed from an approved offline
snapshot. It does not approve a Golden or implement game formulas.

```bash
npm --prefix utility/d4-rulekit/providers/maxroll run build:attest -- \
  --input /private/fixtures/rogue-midgame.json \
  --output /private/fixtures/rogue-midgame.stats.json \
  --snapshot-root /approved/snapshot-store \
  --snapshot-id maxroll-20261023T034150Z \
  --manifest-sha256 638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54 \
  --chromium /path/to/chromium
```

The command is fail-closed and never overwrites output. It uses two fresh
Chromium processes:

- G1 verifies the externally pinned snapshot manifest and calculation resource.
- G2 hashes response bytes delivered to Chromium, observes `scriptParsed`, reads
  the parsed source via CDP, and links the calculation breakpoint's `scriptId`.
- G3 reads the applied profile and resolved equipment from the live calculation
  frame, then compares normalized semantic hashes for equipment, skills,
  skill-bar, Paragon, War Plans, world, specialization, and mercenary state.
- G4 requires a new single-use capture phase after matching G3, 50 unique finite
  raw metrics, all rendered display rows, exact source/replay equality, zero
  completed external egress, and verified teardown.

Outputs have schema `maxroll-character-stats-attestation/v1` and remain
`OBSERVED`. Build exports and stats references contain proprietary state and
values; keep them in a private ignored directory with restrictive permissions.
