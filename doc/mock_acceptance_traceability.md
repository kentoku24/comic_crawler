# Mocked Acceptance Traceability

canonical docs を source of truth とした mocked acceptance set の対応表。
本表は `SPEC.md` / `doc/受け入れテスト計画書.md` の Must 契約を、現在の自動テストへ追跡するための最小トレーサビリティとして扱う。

## Runbook

ローカル / CI で mocked acceptance set をまとめて実行するコマンド:

```bash
python -m manga_watch.run_mocked_acceptance
```

対象 module 一覧だけ見たいとき:

```bash
python -m manga_watch.run_mocked_acceptance --list
```

## Traceability Matrix

| SPEC | Test Plan | Primary tests |
| --- | --- | --- |
| 12.2 `latest` | `TC-LATEST-01` | `tests.test_discord_latest.DiscordLatestTests.test_handle_latest_query_is_read_only_and_uses_only_injected_loaders` |
| 12.2 `latest` | `TC-LATEST-02`, `TC-LATEST-03`, `TC-LATEST-04` | `tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_uses_watchlist_order_and_ignores_disabled_and_orphans` |
| 12.2 `latest` | `TC-LATEST-05`, `TC-LATEST-06` | `tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_returns_empty_message_when_all_works_are_unfetched`; `tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_includes_unfetched_rows_when_mixed_with_saved_results` |
| 12.2 `latest` | `TC-LATEST-07`, `TC-LATEST-08`, `TC-LATEST-09` | `tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_uses_plain_text_and_fallback_labels_without_url` |
| 12.2 `latest` | `TC-LATEST-10`, `TC-LATEST-11` | `tests.test_discord_latest.DiscordLatestTests.test_episode_label_truncation_matches_spec_examples` |
| 12.2 `latest` | `TC-LATEST-12` | `tests.test_discord_latest.DiscordLatestTests.test_build_latest_query_response_warns_for_stale_saved_data` |
| 12.3 Daily notification | `TC-DAILY-01`, `TC-DAILY-02`, `TC-DAILY-03`, `TC-DAILY-04` | `tests.test_runner.RunnerTests.test_run_once_with_discord_outbound_sends_daily_notification_and_run_report`; `tests.test_discord_outbound.DiscordOutboundTests.test_enqueue_daily_notification_dedupes_by_work_id_and_latest_key_even_if_metadata_changes`; `tests.test_check.CheckTests.test_run_check_silently_merges_metadata_without_emitting_update` |
| 12.3 Daily notification | `TC-DAILY-05`, `TC-DAILY-06`, `TC-DAILY-07`, `TC-DAILY-08`, `TC-DAILY-09`, `TC-DAILY-10` | `tests.test_discord_outbound.DiscordOutboundTests.test_build_daily_notification_message_formats_lines_and_truncates_labels` |
| 12.4 `fetch` | `TC-FETCH-01`, `TC-FETCH-02` | `tests.test_discord_fetch.DiscordFetchTests.test_handle_fetch_trigger_routes_only_trimmed_exact_fetch`; `tests.test_runner.RunnerTests.test_handle_fetch_trigger_accepts_when_idle_and_runs_in_background` |
| 12.4 `fetch` | `TC-FETCH-03`, `TC-FETCH-04` | `tests.test_runner.RunnerTests.test_run_coordinator_queues_startup_while_fetch_is_in_progress`; `tests.test_runner.RunnerTests.test_run_coordinator_queues_scheduled_while_fetch_is_in_progress`; `tests.test_runner.RunnerTests.test_queued_fetch_defers_second_run_until_current_run_finishes` |
| 12.5 Run report | `TC-REPORT-01`, `TC-REPORT-04` | `tests.test_runner.RunnerTests.test_run_once_without_updates_only_logs_report`; `tests.test_runner.RunnerTests.test_run_once_with_discord_outbound_sends_daily_notification_and_run_report` |
| 12.5 Run report | `TC-REPORT-02`, `TC-REPORT-03` | `tests.test_runner.RunnerTests.test_run_once_marks_source_errors_as_degraded_while_still_sending_events`; `tests.test_runner.RunnerTests.test_run_once_reports_daily_pending_and_delivery_failure_visibility`; `tests.test_runner.RunnerTests.test_run_once_logs_secondary_failure_when_run_report_delivery_fails` |
| 12.6 Delivery / recovery | `TC-DELIVERY-01`, `TC-DELIVERY-02`, `TC-DELIVERY-03`, `TC-DELIVERY-04` | `tests.test_runner.RunnerTests.test_build_update_event_derives_stable_event_id_from_work_id_and_latest_key`; `tests.test_runner.RunnerTests.test_run_once_persists_only_failed_backends_in_notification_outbox`; `tests.test_runner.RunnerTests.test_run_once_replays_pending_notification_outbox_on_next_run`; `tests.test_runner.RunnerTests.test_run_once_replays_pending_daily_notification_on_next_run`; `tests.test_runner.RunnerTests.test_replay_outbox_once_keeps_discord_daily_pending_messages_untouched`; `tests.test_runner.RunnerTests.test_replay_outbox_module_replays_pending_events` |
| 12.7 State safety | `TC-STATE-01`, `TC-STATE-02`, `TC-STATE-03` | `tests.test_storage.StorageTests.test_save_state_keeps_previous_json_when_write_fails_before_replace`; `tests.test_storage.StorageTests.test_load_state_never_observes_partial_json_during_repeated_writes`; `tests.test_storage.StorageTests.test_concurrent_writers_keep_state_parseable` |
| 12.8 Security | `TC-SEC-01`, `TC-SEC-02`, `TC-SEC-03` | `tests.test_discord_outbound.DiscordOutboundTests.test_discord_channel_client_masks_bot_token_in_transport_error`; `tests.test_discord_outbound.DiscordOutboundTests.test_discord_channel_client_masks_bot_token_in_error_response`; `tests.test_runner.RunnerTests.test_webhook_notifier_masks_webhook_url_in_transport_error`; `tests.test_runner.RunnerTests.test_run_once_redacts_secrets_from_failure_outputs` |

## Scope Notes

- `TC-PERF-*` は `#96` の benchmark harness で扱う。
- `TC-E2E-*` は `#95` の real Discord E2E harness で扱う。
- 本表は mocked automated tests の主判定対象だけを持つ。
