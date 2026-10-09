# Issue #47 / PR #52 — Automated acceptance traceability

**Scope:** OBS Plugin Manager backend. Test runner Windows; OBS process, filesystem production, streaming credentials and release provider are simulated in CI. This file maps existing automated tests to acceptance; real Windows-A evidence must be recorded independently.

**Do not mark PASS until GitHub Actions succeeds on the final PR HEAD.** A successful older commit is not proof for a newer commit.

## Unit acceptance mapping

| ID | Requirement | Main evidence tests |
|---|---|---|
| U01 | REST/WS route through shared service | `test_rest_ws_parity_all_mutations_with_single_service`, `test_websocket_uses_same_plugin_service_as_rest` |
| U02 | Transport typed parity | `test_rest_ws_typed_error_equivalence_for_every_mutation` |
| U03 | Reject client URL/path/binary | `test_websocket_rejects_transport_specific_extra_input`, `test_operations_reject_all_client_input` |
| U04 | Manifest/provenance/compatibility required | `test_invalid_release_metadata_fails_closed`, `test_bad_tree_manifest_fails_before_install` |
| U05 | Core independent of provider/repository address | `test_release_contract_has_no_provider_url_or_token_fields`, `test_unit_release_provider_is_swappable` |
| U06 | Client cannot override managed source | `test_rest_rejects_source_override_for_every_mutation`, `test_websocket_rejects_source_override_for_every_mutation` |
| U07 | Only configured source; no fallback | `test_missing_managed_release_fails_closed_without_fallback`, `test_artifact_failure_does_not_try_another_source` |
| U08 | UI state model | `test_unit_status_supports_required_states`, `test_failed_vendor_probe_sets_verify_failed_until_subsequent_success` |
| U09 | Version/restart status | `test_unit_status_contract_has_full_lifecycle_fields`, `test_version_status_transition` |
| U10 | SHA/corrupt reject before mutation | `test_bad_hash_fails_before_any_installed_file_mutation`, `test_update_rejects_invalid_release_hash_before_touching_v1_or_config` |
| U11 | Update separate from install | `test_update_calls_distinct_host_operation_not_install`, `test_update_same_version_is_rejected_without_false_success` |
| U12 | Backup/restore config byte-for-byte | `test_rollback_preserves_preexisting_config_byte_for_byte`, `test_e2e_update_rollback_restores_v1_bytes` |
| U13 | Failed post-install/update verify → recovery | `test_manual_restart_verify_failure_triggers_rollback_and_restarts_obs`, `test_e2e_post_update_verify_failure_recovers_byte_exact_baseline` |
| U14 | Active output prevents mutations | `test_install_and_rollback_block_active_outputs`, `test_update_rejects_active_outputs_without_mutating_host` |
| U15 | Concurrent mutations deterministic | `test_concurrent_mutations_reject_second_operation`, `test_mutation_timeout_is_typed_and_sanitized` |
| U16 | No secret leak | `test_websocket_unexpected_error_never_logs_or_returns_secret`, `test_update_failure_has_typed_sanitized_error` |

## Automated E2E acceptance mapping

| ID | Requirement | Main evidence tests |
|---|---|---|
| E01 | UI inventory/card data | `test_inventory_schema_is_renderable_without_hardcoded_ui_state`, `test_inventory_only_reports_registered_plugin` |
| E02 | Install → restart-required → Process API → vendor verify | `test_e2e_real_service_install_process_api_restart_verify_and_inventory`, `test_manual_restart_workflow_install_then_process_start_then_verify` |
| E03 | Update v1→v2 config preservation + verify | `test_e2e_update_v1_to_v2_changes_bytes_and_preserves_config`, `test_manual_restart_workflow_update_is_not_an_install_alias`, `test_e2e_v1_to_v2_update_through_service_then_vendor_verify_preserves_config` |
| E04 | Invalid release fails before mutation | `test_bad_hash_fails_before_any_installed_file_mutation`, `test_incompatible_obs_rejected_without_download`, `test_update_rejects_invalid_release_hash_before_touching_v1_or_config` |
| E05 | Configured provider, no direct source fallback | `test_e2e_provider_artifact_is_consumed_from_approved_source_only`, `test_configured_directory_provider_no_external_fallback`, `test_unit_release_provider_is_swappable` |
| E06 | Failed post-update verify auto rollback | `test_e2e_post_update_verify_failure_recovers_byte_exact_baseline` |
| E07 | Manual rollback to baseline | `test_e2e_update_rollback_restores_v1_bytes`, `test_rollback_preserves_preexisting_config_byte_for_byte` |
| E08 | REST/WS operation parity | `test_rest_ws_parity_all_mutations_with_single_service`, `test_rest_ws_typed_error_equivalence_for_every_mutation` |
| E09 | WebSocket request_id correlation | `test_websocket_correlates_multiple_requests_and_preserves_order`, `test_rest_ws_typed_error_equivalence_for_every_mutation` |
| E10 | Bounded HTTP timeout and out-of-scope config safety | `test_e2e_http_update_timeout_is_bounded_and_typed`, `test_rollback_does_not_delete_nonempty_new_user_config` |

## Release/real-device gate

- Current managed distribution repository: `Synclab-VN-dev/StreamOps-OBS-Plugins`. Its GitHub Releases list was empty at audit time, so **no approved StreamOps-built v1/v2 package with Vendor `sorayuki.multi_rtmp` was evidenced**.
- Server-controlled directory and GitHub Release providers are implemented. Missing, empty, or invalid sources fail closed; neither provider falls back to upstream artifacts.
- Synthetic CI proves contracts and filesystem transaction behavior; it does **not** prove real OBS plugin Vendor readiness on Windows-A.
- DEV-F real-A 11 and MANUAL operator 9 remain **NOT RUN**, and PR should remain Draft until these have evidence.
- Backend persistent Activity Log is intentionally out of scope.

## GitHub Releases + available catalog acceptance (new scope, 2026-10-09)

The following 8 UNIT and 7 E2E rows are newly added and **are not covered
by run #460**. All direct test names are defined in
streamops/server/tests/test_issue47_github_releases_acceptance.py.
Only mark new acceptance complete once CI PASS is verified on the new HEAD.

| ID | Requirement | Direct named test |
|---|---|---|
| U17 | Server-controlled GitHubReleaseSource configuration | test_u17_server_only_github_provider_configuration |
| U18 | Correct semver ordering, draft/prerelease policy | test_u18_version_sort_draft_prerelease_policy |
| U19 | Approval/provenance/manifest checks | test_u19_release_identity_provenance_approval_validation |
| U20 | Catalog intersection allowlist and release | test_u20_catalog_intersects_registry_and_release |
| U21 | Empty repo versus typed source errors | test_u21_empty_is_distinct_from_source_failure |
| U22 | Redirect trust policy | test_u22_download_redirect_host_allowlist |
| U23 | Static available route and client-source injection guard | test_u23_static_available_route_and_reject_client_source |
| U24 | SHA identity pinned from discovery to asset bytes | test_u24_mutated_approved_asset_fails_before_mutation |
| E11 | GitHub HTTP release index, manifest and asset fixture | test_e11_discovery_manifest_asset_from_expected_github_api |
| E12 | FastAPI catalog, inventory and allowlist parity | test_e12_catalog_rest_inventory_allowlist_parity |
| E13 | Empty/incompatible/installed/update catalog states | test_e13_catalog_empty_incompatible_installed_update |
| E14 | Install, real filesystem transaction, restart and vendor probe | test_e14_github_provider_install_restart_verify_real_filesystem |
| E15 | Update/verify/manual rollback and failed vendor auto rollback | test_e15_github_provider_v1_v2_update_verify_rollback |
| E16 | Corrupt release/source outage does not mutate filesystem | test_e16_github_release_failure_no_mutation_no_fallback |
| E17 | Swap GitHub to directory provider without API contract changes | test_e17_provider_swap_does_not_change_rest_ws_api |

### Managed GitHub release publication contract

Windows A runtime must select source via server-side environment settings:
- STREAMOPS_OBS_PLUGIN_SOURCE_PROVIDER = github-release
- STREAMOPS_OBS_PLUGIN_SOURCE_LOCATION = Synclab-VN-dev/StreamOps-OBS-Plugins
- Optional credential variable NAME configured by STREAMOPS_OBS_PLUGIN_GITHUB_TOKEN_ENV;
  never log, echo or put its secret value in REST/WS.

Release tag: obs-multi-rtmp/v<version>. Must include exactly the assets
obs-multi-rtmp.release.json and the ZIP named by manifest.artifact_name.
JSON manifest must match PluginRelease fields and metadata approval flags
approved=true, redistribution_approved=true, plus exact tree metadata
file_count/relative_paths/tree_sha256.

GitHubReleaseSource downloads only from the configured GitHub API release
asset ID and enforces SHA-256/approved manifest. No upstream fallback.
CI uses mocked GitHub HTTP and OBS/Vendor; DEV-F must prove source/version/SHA
against **real Synclab GitHub Releases** on Windows A. Current audited release
count is zero, so destructive real-A install/update/rollback are BLOCKED until
approved release(s) are available.

## Legacy adoption acceptance (P0)

These tests use a real isolated filesystem tree, config fixture, backup, journal,
and rollback. They do not mutate Windows A and do not qualify any D01–D15 real-A
acceptance as PASS.

| ID | Requirement | Direct evidence |
|---|---|---|
| AD01 | Legacy files without journal are unmanaged | `test_ad01_detects_legacy_tree_without_journal` |
| AD02 | Explicit adoption snapshots and commits a legacy journal | `test_ad02_adopt_creates_verified_snapshot_and_legacy_journal` |
| AD03 | Repeated adoption is idempotent | `test_ad03_second_adopt_is_idempotent` |
| AD04 | Exact approved bytes are promoted without rewrite | `test_ad04_exact_approved_legacy_is_not_rewritten` |
| AD05 | Mismatched legacy remains unchanged until approved install | `test_ad05_mismatched_legacy_remains_unchanged_until_install` |
| AD06 | Missing/corrupt backup fails before mutation | `test_ad06_corrupt_backup_fails_without_changing_legacy` |
| AD07 | Streaming/recording guard | `test_ad07_active_outputs_reject_adopt` |
| AD08 | OBS-held DLL guard | `test_ad08_installer_rejects_adopt_while_obs_holds_dll` |
| AD09 | Legacy to approved v1 transaction chain | `test_ad09_legacy_to_approved_creates_real_transaction_chain`, `test_ad09_service_stops_obs_before_legacy_to_approved_install` |
| AD10 | Failed verification restores legacy bytes | `test_ad10_verify_failure_restores_legacy_byte_for_byte` |
| AD11 | Manual rollback restores files and config baseline | `test_ad11_manual_rollback_restores_legacy_and_config` |
| AD12 | Pending/crashed transaction fails closed and recovers explicitly | `test_ad12_pending_without_mutation_is_detected_and_aborted_safely`, `test_ad12_mutation_pending_restores_only_verified_backup` |
| AD13 | Concurrent mutation is rejected | `test_ad13_concurrent_adopt_rejects_second_mutation` |
| AD14 | Restart/vendor failure is typed, sanitized, and recovered | `test_restart_failure_is_typed_and_attempts_safe_rollback`, `test_ad14_vendor_failure_is_typed_and_restores_legacy` |
| AD15 | REST/WS adoption parity and input sanitization | `test_ad15_rest_and_websocket_adopt_contract` |
