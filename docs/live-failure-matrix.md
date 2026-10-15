# T16 controlled failure and isolation audit

The source failure table is in `docs/specs/realtime-openttd-telemetry.md`, §5.
The tests below use controlled processes and Admin peers. PostgreSQL cases use
isolated schemas. They do not launch production OpenTTD.

| Source condition | Passing acceptance evidence |
| --- | --- |
| Startup, bind or asset failure | `test_live_runner.py::test_cache_only_asset_failure_never_launches_process`; `test_live_launch_preparation.py::test_fixed_port_collision_and_release`; `test_live_service.py::test_live_creation_failure_launches_nothing` |
| Authentication failure | `test_admin_observer.py::test_rejection_reason_is_classified_without_password_retry`; `test_live_runner.py::test_observer_or_child_failure_stops_only_owned_process_and_cleans_resources` |
| Protocol, identity or malformed known packet | `test_admin_observer.py::test_protocol_version_frequencies_and_welcome_identity_must_match`; `test_admin_protocol.py::test_known_trailing_data_is_ignored_but_malformed_known_packet_fails`; `test_live_runner.py::test_reconnect_does_not_retry_semantic_failure` |
| Recovered or exhausted observation loss | `test_live_service.py::test_postgres_recovered_gap_stays_ordered_and_marks_success_incomplete`; `test_live_service.py::test_postgres_reconnect_exhaustion_keeps_gap_and_typed_failure`; `test_live_runner.py::test_cancellation_during_reconnect_backoff_joins_observer` |
| Database failure before launch | `test_live_service.py::test_live_creation_failure_launches_nothing` |
| Transient telemetry database failure | `test_telemetry_processor.py::test_retry_reuses_identical_batch_and_recovery_does_not_mark_fatal`; `test_telemetry_repository.py::test_committed_but_unacknowledged_batch_retries_without_duplicate_counters` |
| Exhausted, permanent or full-queue telemetry failure | `test_live_runner.py::test_fatal_telemetry_write_cannot_return_live_success`; `test_telemetry_processor.py::test_capacity_includes_inflight_and_health_remains_responsive`; `test_telemetry_processor.py::test_permanent_failure_is_not_retried_and_cancellation_leaves_no_tasks` |
| Normal completion or missing required observations | `test_live_runner.py::test_one_owned_child_reaches_date_target_and_returns_injected_final_result`; `test_live_service.py::test_postgres_live_processor_writes_before_final_simulation_row` (`complete=False/True`); `test_live_isolation.py::test_postgres_controlled_live_secret_stays_out_of_every_durable_and_cli_surface` verifies a successful Date-only controlled run stays incomplete with CLI exit 3. |
| Timeout, SIGINT, SIGTERM | `test_live_runner.py::test_running_timeout_attempts_one_bounded_partial_save_before_quit`; `test_experiment_cli.py::test_catchable_live_signal_sets_runner_token_and_restores_handlers`; `test_live_isolation.py::test_two_controlled_peers_keep_ports_processes_and_cancellation_separate` |
| Expected versus unexpected shutdown/EOF | `test_live_runner.py::test_unpause_process_or_observer_failure_aborts_before_running`; `test_live_runner.py::test_post_target_observer_eof_does_not_discard_explicit_final_save`; `test_admin_observer.py::test_clean_eof_is_distinct_from_malformed_known_packet` |
| Save or parser failure | `test_live_runner.py::test_explicit_save_failure_never_returns_success`; `test_live_runner.py::test_final_result_failure_cannot_become_success`; `test_final_result.py::test_parser_child_is_reaped_on_cancellation` |
| Final database commit failure | `test_live_service.py::test_postgres_terminal_failure_keeps_telemetry_and_publishes_success_evidence`; `test_live_isolation.py::test_postgres_parallel_runs_keep_telemetry_terminal_failure_and_recovery_isolated` |
| Terminal recovery and conflict | `test_outcome_recovery.py::test_postgres_recovery_is_idempotent_and_keeps_telemetry`; `test_outcome_recovery.py::test_postgres_concurrent_recovery_creates_one_result`; `test_live_isolation.py::test_postgres_parallel_runs_keep_telemetry_terminal_failure_and_recovery_isolated` |
| Abrupt supervisor death and abandoned workspace | `test_parent_death_exec.py::test_one_shot_exec_child_dies_when_supervisor_is_sigkilled`; `test_workspace_recovery.py::test_active_workspace_is_retained_then_cleaned_after_owned_group_exits`; `test_workspace_recovery.py::test_name_swap_during_fd_erase_never_erases_replacement` |

| Overlapping failures | Required precedence and evidence |
| --- | --- |
| Cancellation after the final result is ready | `test_live_runner.py::test_cancellation_after_final_result_before_return_cannot_succeed` retains `CANCELLED`. |
| Timeout plus forced cleanup or partial save | `test_live_runner.py::test_running_timeout_attempts_one_bounded_partial_save_before_quit` and `test_live_runner.py::test_signal_error_does_not_skip_later_cleanup` retain `TIMEOUT`; cleanup is diagnostic. |
| Observer loss during storage failure | `test_live_runner.py::test_fatal_telemetry_write_cannot_return_live_success` and `test_live_service.py::test_failed_telemetry_summary_and_terminal_failure_stays_failed` retain persistence failure. |
| Protocol failure plus cleanup error | `test_live_runner.py::test_prelaunch_cleanup_error_preserves_original_failure` retains `PROTOCOL_FAILURE`. |
| Reconnect exhausted plus later process exit | `test_live_runner.py::test_reconnect_exhaustion_is_observer_lost_without_second_world` retains `OBSERVER_LOST`. |
| Finalization failure plus process cleanup | `test_live_runner.py::test_final_result_failure_cannot_become_success` retains `FINALIZATION_FAILURE`. |
| Successful execution plus failed terminal commit | `test_live_service.py::test_postgres_terminal_failure_keeps_telemetry_and_publishes_success_evidence` and the new parallel-run test retain the success evidence in a manifest while reporting persistence failure. |
| Typed execution failure plus failed terminal commit | `test_live_service.py::test_failed_execution_and_failed_terminal_write_preserve_original_code` retains the original failure in the manifest. |
| Manifest publication failure | `test_live_service.py::test_terminal_db_and_manifest_failure_never_claims_durable_outcome` does not report false success. |
| Recovery conflict | `test_outcome_recovery.py::test_conflicting_terminal_row_is_not_overwritten` and the new parallel-run test leave conflicting DB state unchanged. |

Cross-run tests also assert rejection of one run's password by the other's Admin
peer, separate leased game/Admin ports, process IDs, private
workspaces, passwords, run IDs, sequence domains, artifacts, manifests and database
terminal outcomes. A rolled-back terminal transaction for one run leaves the other
successful; explicit recovery of the first does not change the second. Cancellation
of one controlled child does not cancel or signal the other.

Security regression evidence includes `test_live_launch_preparation.py` for exact
0700/0600 permissions and loopback settings; `test_admin_observer.py` for rejection
of non-loopback hosts and read-only packets; `test_live_isolation.py` for secret
absence from actual controlled outcomes/output and cross-run process isolation;
`test_live_service.py`, `test_experiment_cli.py`, and `test_outcome_manifest.py` for
sanitized persisted/result/CLI/manifest boundaries; and `test_outcome_recovery.py`
for path, artifact and database conflict rejection.
`test_live_launch_preparation.py::test_fixed_port_collision_and_release` verifies
external port collision, while
`test_runtime_assets.py::test_concurrent_processes_share_verified_publication`
verifies concurrent cache publication.

Manifest v1 remains trusted local recovery evidence. Its schema, paths, artifacts,
hashes, run/config identity and DB conflicts are checked; plausible edits to
manifest-only outcome fields have no external cryptographic anchor in v1.

The direct child is protected on abrupt Linux supervisor death. Arbitrary orphaned
descendants are outside that guarantee. T17 owns the real production OpenTTD proof.
