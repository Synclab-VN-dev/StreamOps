# Issue #35 — Multiple RTMP runtime API spike

Status: **implementation harness ready; Real-A evidence pending**

This document describes Gate 3 only. It does not define or implement production StreamOps
multistream backend/UI.

## Pinned candidate source

Vendored under:

~~~text
util/obs-multi-rtmp-websocket/
~~~

Source provenance is recorded in UPSTREAM.md / UPSTREAM.json.

Pinned candidate commit:

~~~text
davidcool/obs-multi-rtmp-websocket-support
d81f40b769c4f1460132d8bc06207027c681e359
~~~

The nested upstream .git directory is intentionally not included. Four documentation-only
binary images are omitted; build/runtime source is retained.

## Source-review findings to verify on Real-A

These are observations from the pinned source, not yet production decisions.

1. The candidate registers vendor sorayuki.multi_rtmp with 16 requests:
   list/state/start/stop/toggle/start-all/stop-all/add/clone/rename/key/service-param/delete/
   sync-start/sync-stop/stats.
2. Target IDs are serialized into obs-multi-rtmp.json and loaded back; GenerateId() is used
   for newly added/cloned targets. This suggests restart persistence but Gate 3 must prove it on A.
3. Names are not enforced unique. Name lookup returns the first matching widget, so name must not
   be treated as persistent StreamOps identity.
4. start_target / stop_target queue work onto the OBS UI thread and return
   start_requested / stop_requested. Acceptance must poll actual state after the request.
5. The current README field examples do not exactly match implementation: source uses
   isRunning, bitrateValue, fpsValue; the runner normalizes both source and documented aliases.
6. list_targets exposes server URL but not the stream key. update_stream_key response does not
   echo the new key. Runner output/report redacts credential fields and known secret values.

## Real-A execution order

### 1. Automated/unit checks

~~~powershell
python -m pytest streamops/server/tests/test_issue35_multirtmp_api_spike.py -q
~~~

### 2. P1/P2 — upstream/native phase

Keep the pinned upstream plugin from Gate 1 installed.

~~~powershell
python scripts/e2e/issue35_multirtmp_api_spike.py --phase native
~~~

This phase:

- backs up current obs-multi-rtmp.json;
- creates only issue35-* local targets;
- probes GetOutputList/GetOutputStatus;
- tries per-output native start/stop only when output names are unambiguous;
- restarts OBS once for identity evidence;
- probes upstream CallVendorRequest;
- restores the original plugin config in finally.

### 3. Build candidate from vendored source

Run with PowerShell 7.2+:

~~~powershell
pwsh scripts/e2e/issue35_build_candidate.ps1
~~~

Record the emitted CandidateDll and SHA-256.

### 4. Temporarily install candidate

~~~powershell
pwsh scripts/e2e/issue35_candidate_swap.ps1 -Action InstallCandidate -CandidateDll "<CandidateDll>"
~~~

Record the emitted BackupDir.

The helper refuses mutation while OBS is streaming or recording, stops OBS, swaps only the plugin DLL,
starts OBS again, and verifies the copied candidate hash. Gate 1 pinned-manifest status can be
non-LOADED during this temporary candidate phase by design.

### 5. P3/P4/P5 — Vendor API phase

~~~powershell
python scripts/e2e/issue35_multirtmp_api_spike.py --phase vendor
~~~

The runner tests:

- list/add/update/delete;
- stream-key update without response leakage;
- rename ID stability;
- independent start/stop A and B;
- start-all/stop-all;
- state/stats polling;
- ID persistence across OBS restart;
- duplicate-name behavior;
- cleanup of all issue35-* targets.

Raw evidence is written only under:

~~~text
.streamops/issue-35/
~~~

which is already ignored by Git.

### 6. Restore upstream

~~~powershell
pwsh scripts/e2e/issue35_candidate_swap.ps1 -Action RestoreUpstream -BackupDir "<BackupDir>"
~~~

Restore acceptance requires:

- restored DLL SHA-256 equals the saved upstream SHA;
- OBS returns READY;
- Gate 1 plugin endpoint returns LOADED again.

## Capability decision rule

Gate 3 does not choose an architecture before evidence exists.

~~~text
Native OBS has stable per-target identity + independent control?
  yes -> native remains a candidate
  no  -> evaluate Vendor candidate

Vendor candidate:
  stable ID across restart?
  independent start/stop?
  add/update/delete?
  state/stats?
  credential-safe?
  restore-safe?

Only then write the final technical decision.
~~~

## Open risk: license

The imported candidate is GPL-2.0 licensed. Vendoring/modifying/distributing it inside StreamOps can
have licensing implications for distribution and derivative-work boundaries. This PR keeps the
upstream license and provenance, but merge/release policy must be reviewed before treating the
vendored plugin as a production dependency.
