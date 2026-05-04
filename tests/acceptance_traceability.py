from __future__ import annotations

ACCEPTANCE_TRACEABILITY = {
    "TC-LATEST-01": {
        "layer": "mocked_discord_integration",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_handle_latest_query_is_read_only_and_uses_only_injected_loaders",
        ],
    },
    "TC-LATEST-02": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_uses_watchlist_order_and_ignores_disabled_and_orphans",
        ],
    },
    "TC-LATEST-03": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_uses_watchlist_order_and_ignores_disabled_and_orphans",
        ],
    },
    "TC-LATEST-04": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_uses_watchlist_order_and_ignores_disabled_and_orphans",
        ],
    },
    "TC-LATEST-05": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_returns_empty_message_when_all_works_are_unfetched",
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_includes_unfetched_rows_when_mixed_with_saved_results",
        ],
    },
    "TC-LATEST-06": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_returns_empty_message_when_all_works_are_unfetched",
        ],
    },
    "TC-LATEST-07": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_uses_watchlist_order_and_ignores_disabled_and_orphans",
        ],
    },
    "TC-LATEST-08": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_uses_plain_text_and_fallback_labels_without_url",
        ],
    },
    "TC-LATEST-09": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_uses_plain_text_and_fallback_labels_without_url",
        ],
    },
    "TC-LATEST-10": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_episode_label_truncation_matches_spec_examples",
        ],
    },
    "TC-LATEST-11": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_episode_label_truncation_matches_spec_examples",
        ],
    },
    "TC-LATEST-12": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_warns_for_stale_saved_data",
        ],
    },
    "TC-DAILY-01": {
        "layer": "orchestration",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_without_updates_only_logs_report",
            "tests.test_runner.RunnerTests.test_run_once_with_discord_outbound_sends_daily_notification_and_run_report",
        ],
    },
    "TC-DAILY-02": {
        "layer": "orchestration",
        "tests": [
            "tests.test_check.CheckTests.test_apply_item_transition_reports_updates_when_latest_changes",
            "tests.test_runner.RunnerTests.test_run_once_with_discord_outbound_sends_daily_notification_and_run_report",
        ],
    },
    "TC-DAILY-03": {
        "layer": "orchestration",
        "tests": [
            "tests.test_discord_outbound.DiscordOutboundTests.test_enqueue_daily_notification_dedupes_by_work_id_and_latest_key_even_if_metadata_changes",
        ],
    },
    "TC-DAILY-04": {
        "layer": "orchestration",
        "tests": [
            "tests.test_check.CheckTests.test_run_check_silently_merges_metadata_without_emitting_update",
        ],
    },
    "TC-DAILY-05": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_outbound.DiscordOutboundTests.test_build_daily_notification_message_formats_lines_and_truncates_labels",
        ],
    },
    "TC-DAILY-06": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_outbound.DiscordOutboundTests.test_build_daily_notification_message_formats_lines_and_truncates_labels",
        ],
    },
    "TC-DAILY-07": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_outbound.DiscordOutboundTests.test_build_daily_notification_message_formats_lines_and_truncates_labels",
        ],
    },
    "TC-DAILY-08": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_outbound.DiscordOutboundTests.test_build_daily_notification_message_formats_lines_and_truncates_labels",
        ],
    },
    "TC-DAILY-09": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_outbound.DiscordOutboundTests.test_build_daily_notification_message_formats_lines_and_truncates_labels",
        ],
    },
    "TC-DAILY-10": {
        "layer": "formatter",
        "tests": [
            "tests.test_discord_outbound.DiscordOutboundTests.test_build_daily_notification_message_formats_lines_and_truncates_labels",
        ],
    },
    "TC-FETCH-01": {
        "layer": "mocked_discord_integration",
        "tests": [
            "tests.test_runner.RunnerTests.test_handle_fetch_trigger_accepts_when_idle_and_runs_in_background",
        ],
    },
    "TC-FETCH-02": {
        "layer": "mocked_discord_integration",
        "tests": [
            "tests.test_runner.RunnerTests.test_handle_fetch_trigger_accepts_when_idle_and_runs_in_background",
            "tests.test_discord_fetch.DiscordFetchTests.test_handle_fetch_trigger_accepts_whitespace_trimmed_fetch",
        ],
    },
    "TC-FETCH-03": {
        "layer": "orchestration",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_coordinator_queues_scheduled_while_fetch_is_in_progress",
            "tests.test_runner.RunnerTests.test_run_coordinator_queues_startup_while_fetch_is_in_progress",
        ],
    },
    "TC-FETCH-04": {
        "layer": "persistence",
        "tests": [
            "tests.test_runner.RunnerTests.test_queued_fetch_defers_second_run_until_current_run_finishes",
        ],
    },
    "TC-REPORT-01": {
        "layer": "orchestration",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_without_updates_only_logs_report",
            "tests.test_runner.RunnerTests.test_run_once_with_discord_outbound_sends_daily_notification_and_run_report",
            "tests.test_runner.RunnerTests.test_run_once_sends_run_report_to_discord_when_checker_raises",
        ],
    },
    "TC-REPORT-02": {
        "layer": "orchestration",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_without_updates_only_logs_report",
            "tests.test_runner.RunnerTests.test_run_once_marks_source_errors_as_degraded_while_still_sending_events",
        ],
    },
    "TC-REPORT-03": {
        "layer": "orchestration",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_reports_daily_pending_and_delivery_failure_visibility",
            "tests.test_runner.RunnerTests.test_run_once_logs_secondary_failure_when_run_report_delivery_fails",
        ],
    },
    "TC-REPORT-04": {
        "layer": "formatter",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_with_discord_outbound_sends_daily_notification_and_run_report",
            "tests.test_runner.RunnerTests.test_run_once_reports_daily_pending_and_delivery_failure_visibility",
        ],
    },
    "TC-DELIVERY-01": {
        "layer": "orchestration",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_reports_daily_pending_and_delivery_failure_visibility",
        ],
    },
    "TC-DELIVERY-02": {
        "layer": "persistence",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_persists_only_failed_backends_in_notification_outbox",
            "tests.test_runner.RunnerTests.test_run_once_reports_daily_pending_and_delivery_failure_visibility",
        ],
    },
    "TC-DELIVERY-03": {
        "layer": "persistence",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_replays_pending_notification_outbox_on_next_run",
            "tests.test_runner.RunnerTests.test_run_once_replays_pending_daily_notification_on_next_run",
            "tests.test_runner.RunnerTests.test_replay_outbox_module_replays_pending_events",
        ],
    },
    "TC-DELIVERY-04": {
        "layer": "orchestration",
        "tests": [
            "tests.test_runner.RunnerTests.test_build_update_event_derives_stable_event_id_from_work_id_and_latest_key",
        ],
    },
    "TC-STATE-01": {
        "layer": "persistence",
        "tests": [
            "tests.test_storage.StorageTests.test_save_state_keeps_previous_json_when_write_fails_before_replace",
        ],
    },
    "TC-STATE-02": {
        "layer": "persistence",
        "tests": [
            "tests.test_storage.StorageTests.test_load_state_never_observes_partial_json_during_repeated_writes",
        ],
    },
    "TC-STATE-03": {
        "layer": "persistence",
        "tests": [
            "tests.test_storage.StorageTests.test_concurrent_writers_keep_state_parseable",
        ],
    },
    "TC-SEC-01": {
        "layer": "security",
        "tests": [
            "tests.test_discord_outbound.DiscordOutboundTests.test_discord_channel_client_masks_bot_token_in_transport_error",
            "tests.test_discord_outbound.DiscordOutboundTests.test_discord_channel_client_masks_bot_token_in_error_response",
            "tests.test_runner.RunnerTests.test_run_once_redacts_secrets_from_failure_outputs",
        ],
    },
    "TC-SEC-02": {
        "layer": "security",
        "tests": [
            "tests.test_runner.RunnerTests.test_webhook_notifier_masks_webhook_url_in_transport_error",
            "tests.test_runner.RunnerTests.test_run_once_redacts_secrets_from_failure_outputs",
        ],
    },
    "TC-SEC-03": {
        "layer": "security",
        "tests": [
            "tests.test_runner.RunnerTests.test_run_once_redacts_secrets_from_failure_outputs",
        ],
    },
}
