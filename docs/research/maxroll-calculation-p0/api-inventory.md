# Maxroll P0 API inventory

Captured on 2026-10-21 (Asia/Ho_Chi_Minh). This inventory records observed
behavior only. It does not claim that any route is official, stable, or licensed
for production use.

## `GET https://planners.maxroll.gg/`

- Purpose: host connectivity/root health observation.
- Input schema: none observed.
- Output schema: JSON object with boolean field `root`.
- Authentication: no credentials, authorization header, or caller-supplied
  cookie required for the observed HTTP 200 response.
- Evidence: `evidence/network.txt` (NET-04).
- Confidence: **CONFIRMED** for the single observed request.
- Returns calculated stats: **No**.

## `GET https://planners.maxroll.gg/profiles/load/d4/{buildId}`

- Purpose: load a saved public Diablo IV planner profile.
- Input schema: path parameter `buildId`; observed value was an eight-character
  alphanumeric ID sourced from a public planner link. Other lengths and
  character constraints were not tested.
- Output schema: JSON object with profile metadata. `data` and `metadata` are
  JSON-encoded strings. Parsed `data` includes `profiles`, an `items` pool,
  `options`, `pinnedStats`, `skillTree`, `skillBar`, `paragon`, and other build
  input/configuration structures. See the sanitized field/type inventory.
- Authentication: no credentials, authorization header, or caller-supplied
  cookie required for the observed public profile response. Private profiles
  were not tested, and broader authentication requirements are unknown.
- Evidence: `evidence/profile-response.json` (API-01, API-02).
- Confidence: **CONFIRMED** for the observed public build; support/stability is
  **UNKNOWN** because no official API documentation was identified.
- Returns calculated stats: **NOT VERIFIED**. No exact calculation-result or
  Character Stats output fields were found in the observed response.

## Calculation endpoint

- URL and method: **UNKNOWN**; no endpoint was identified.
- Purpose: expected to calculate Character Stats, if such a server endpoint
  exists.
- Input schema: **UNKNOWN**.
- Output schema: **UNKNOWN**.
- Authentication: **UNKNOWN**.
- Evidence: `evidence/network.txt` records the policy blocker; the profile
  schema in `evidence/profile-response.json` does not contain verified
  calculation output.
- Confidence: **UNKNOWN**.
- Returns calculated stats: **NOT VERIFIED**.

The Profile API must not be treated as a Calculation API. Browser network
inspection was intentionally stopped at the published access restriction.
