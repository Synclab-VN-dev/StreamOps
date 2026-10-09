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
- Server-controlled local managed directory source can be configured with `STREAMOPS_OBS_PLUGIN_RELEASE_DIR`, containing `obs-multi-rtmp/release.json` and its SHA-pinned zip. Missing source must fail closed. Direct Github Release provider is not yet implemented.
- Synthetic CI proves contracts and filesystem transaction behavior; it does **not** prove real OBS plugin Vendor readiness on Windows-A.
- DEV-F real-A 11 and MANUAL operator 9 remain **NOT RUN**, and PR should remain Draft until these have evidence.
- Backend persistent Activity Log is intentionally out of scope.
