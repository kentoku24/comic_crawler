import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import requests

from manga_watch.discord_outbound import DiscordOutboundConfig
from manga_watch.notifier import (
    NotifierConfig,
    StdoutNotifier,
    WebhookNotifier,
    build_notifier,
    build_update_event,
)
from manga_watch.runner import (
    FETCH_ACCEPTED_MESSAGE,
    TRIGGER_SOURCE_DISCORD_FETCH,
    TRIGGER_SOURCE_SCHEDULED,
    TRIGGER_SOURCE_STARTUP,
    RunCoordinator,
    RunnerConfig,
    replay_outbox_once,
    run_once,
    start_fetch_run,
)
from manga_watch.storage import load_state, save_state


class FakeNotifier:
    def __init__(self, fail_on_index=None):
        self.fail_on_index = fail_on_index
        self.events = []

    def send(self, event):
        if self.fail_on_index is not None and len(self.events) == self.fail_on_index:
            raise RuntimeError("notifier backend failed")
        self.events.append(event)


class SecretLeakingNotifier:
    def __init__(self, message):
        self.message = message

    def send(self, event):
        raise RuntimeError(self.message)


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def post(self, url, json=None, timeout=None, allow_redirects=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected webhook request")
        return self.responses.pop(0)


class FakeDiscordClient:
    def __init__(self, *, fail_on_call=None, fail_channels=None, bot_user_id="bot-user", channel_messages=None):
        self.fail_on_call = fail_on_call
        self.fail_channels = set(fail_channels or [])
        self.bot_user_id = bot_user_id
        self.channel_messages = {
            channel_id: [dict(message) for message in messages]
            for channel_id, messages in (channel_messages or {}).items()
        }
        self.calls = []

    def send_message(self, channel_id, content):
        self.calls.append(
            {
                "channel_id": channel_id,
                "content": content,
            }
        )
        if self.fail_on_call is not None and len(self.calls) - 1 == self.fail_on_call:
            raise RuntimeError("discord delivery failed")
        if channel_id in self.fail_channels:
            raise RuntimeError(f"discord delivery failed for {channel_id}")
        self.channel_messages.setdefault(channel_id, []).insert(
            0,
            {
                "id": str(len(self.channel_messages.get(channel_id, [])) + 1),
                "content": content,
                "author": {"id": self.bot_user_id},
            },
        )

    def get_current_user_id(self):
        return self.bot_user_id

    def list_channel_messages(self, channel_id, *, after=None, limit=50):
        del after
        return [dict(message) for message in self.channel_messages.get(channel_id, [])[:limit]]


class SecretLeakingDiscordClient:
    def __init__(self, token):
        self.token = token
        self.calls = []

    def send_message(self, channel_id, content):
        self.calls.append(
            {
                "channel_id": channel_id,
                "content": content,
            }
        )
        if channel_id == "main-channel":
            raise RuntimeError(f"discord auth failed with Authorization: Bot {self.token}")


class RunnerTests(unittest.TestCase):
    def wait_until(self, predicate, *, timeout=1.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition was not met before timeout")

    def test_runner_module_runs_until_config_validation(self):
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("MANGA_WATCH_NOTIFIER_BACKENDS", None)
        env.pop("MANGA_WATCH_WEBHOOK_URL", None)

        result = subprocess.run(
            [sys.executable, "-m", "manga_watch.runner"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("[runner] configuration error:", result.stderr)
        self.assertIn("MANGA_WATCH_NOTIFIER_BACKENDS", result.stderr)

    def test_run_once_records_run_summary_when_recorder_is_injected(self):
        recorded = []

        def checker(_watchlist_path):
            return {"updates": [], "errors": {"sources": [], "run": []}}

        outcome = run_once(
            self.make_config(),
            checker=checker,
            state_loader=lambda: {"version": 2, "works": {}, "last_run_at": None, "notification_outbox": [], "discord_delivery": {"daily_notification": {"delivered_latest_keys": {}, "pending_messages": []}}},
            state_saver=lambda _state: None,
            run_recorder=lambda summary: recorded.append(dict(summary)) or "run-1",
            report_logger=lambda _message: None,
            error_logger=lambda _message: None,
        )

        self.assertEqual("run-1", outcome["runId"])
        self.assertEqual(1, len(recorded))
        self.assertTrue(recorded[0]["ok"])

    def make_config(self, *, with_discord=False):
        return RunnerConfig(
            timezone_name="Asia/Tokyo",
            watchlist_path="/tmp/watchlist.json",
            crawl_schedule="0 19 * * *",
            crawl_interval=None,
            run_on_startup=True,
            notifier_config=NotifierConfig(backends=("stdout",)),
            discord_outbound_config=(
                DiscordOutboundConfig(
                    bot_token="discord-bot-token",
                    main_channel_id="main-channel",
                    run_report_channel_id="run-report-channel",
                )
                if with_discord
                else None
            ),
        )

    def make_notification(
        self,
        *,
        mode="important_only",
        allowed_update_types=None,
        should_notify=True,
        applied_via="mode",
        reason="test notification policy",
    ):
        return {
            "mode": mode,
            "allowed_update_types": allowed_update_types,
            "should_notify": should_notify,
            "applied_via": applied_via,
            "reason": reason,
        }

    def make_update(
        self,
        *,
        update_type="main_story",
        default_notify=True,
        latest_key="episode-2",
        episode_title="第2話",
        classification_reason=None,
        notification=None,
    ):
        update = {
            "id": "work-1",
            "from": {
                "seriesTitle": "作品A",
                "episodeTitle": "第1話",
                "latestKey": "episode-1",
            },
            "to": {
                "series_title": "作品A",
                "episode_title": episode_title,
                "latest_key": latest_key,
                "url": "https://example.com/2",
                "update_type": update_type,
                "default_notify": default_notify,
            },
            "update_type": update_type,
            "default_notify": default_notify,
            "notification": dict(
                notification
                or self.make_notification(
                    should_notify=default_notify,
                )
            ),
        }
        if classification_reason is not None:
            update["classification_reason"] = classification_reason
            update["to"]["classification_reason"] = classification_reason
        return update

    def make_state(self):
        return {
            "version": 2,
            "works": {
                "work-1": {
                    "latest": {"series_title": "作品A", "episode_title": "第2話"},
                    "history": [],
                    "health": {
                        "last_checked_at": 1_700_000_000,
                        "last_success_at": 1_700_000_000,
                        "consecutive_failures": 0,
                    },
                }
            },
            "last_run_at": None,
            "notification_outbox": [],
            "discord_delivery": {
                "daily_notification": {
                    "delivered_latest_keys": {},
                    "pending_messages": [],
                }
            },
        }

    def make_state_store(self, state=None):
        store = json.loads(json.dumps(state or self.make_state()))

        def load_from_store():
            return json.loads(json.dumps(store))

        def save_to_store(next_state):
            store.clear()
            store.update(json.loads(json.dumps(next_state)))

        return store, load_from_store, save_to_store

    def test_build_update_event_derives_stable_event_id_from_work_id_and_latest_key(self):
        detected_at = "2023-11-14T22:13:20Z"
        first = build_update_event(
            self.make_update(latest_key="episode-2", episode_title="第2話"),
            detected_at=detected_at,
        )
        second = build_update_event(
            self.make_update(latest_key="episode-2", episode_title="第2話 改題"),
            detected_at=detected_at,
        )

        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual("work-1", first.work_id)
        self.assertEqual("episode-2", first.latest_key)
        self.assertEqual("作品A", first.series_title)
        self.assertEqual(detected_at, first.detected_at)
        self.assertEqual("第1話", first.as_payload()["from"]["episode_title"])
        self.assertEqual("第2話", first.as_payload()["to"]["episode_title"])

    def test_stdout_notifier_writes_json_line(self):
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )
        stream = io.StringIO()

        StdoutNotifier(stream=stream).send(event)

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("work-1", payload["work_id"])
        self.assertEqual("episode-2", payload["latest_key"])
        self.assertEqual("作品A", payload["series_title"])
        self.assertTrue(payload["notification"]["should_notify"])

    def test_webhook_notifier_treats_2xx_as_success(self):
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )
        session = FakeSession(responses=[FakeResponse(204)])
        notifier = WebhookNotifier("https://example.com/hook", timeout=7, session=session)

        notifier.send(event)

        self.assertEqual(1, len(session.calls))
        self.assertEqual("https://example.com/hook", session.calls[0]["url"])
        self.assertEqual(7, session.calls[0]["timeout"])
        self.assertFalse(session.calls[0]["allow_redirects"])
        self.assertEqual(event.as_payload(), session.calls[0]["json"])

    def test_build_notifier_fans_out_to_all_configured_backends(self):
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )
        stream = io.StringIO()
        session = FakeSession(responses=[FakeResponse(202)])
        notifier = build_notifier(
            NotifierConfig(
                backends=("stdout", "webhook"),
                webhook_url="https://example.com/hook",
                webhook_timeout=7,
            ),
            stream=stream,
            session=session,
        )

        notifier.send(event)

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual("work-1", payload["work_id"])
        self.assertEqual(1, len(session.calls))
        self.assertEqual(event.as_payload(), session.calls[0]["json"])

    def test_webhook_notifier_raises_on_non_2xx(self):
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )
        session = FakeSession(responses=[FakeResponse(500, "server exploded")])
        notifier = WebhookNotifier("https://example.com/hook", session=session)

        with self.assertRaisesRegex(RuntimeError, "Webhook returned HTTP 500"):
            notifier.send(event)

    def test_webhook_notifier_raises_on_transport_error(self):
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )
        session = FakeSession(error=requests.Timeout("timed out"))
        notifier = WebhookNotifier("https://example.com/hook", session=session)

        with self.assertRaisesRegex(RuntimeError, "Webhook delivery failed"):
            notifier.send(event)

    def test_webhook_notifier_masks_webhook_url_in_transport_error(self):
        webhook_url = "https://discord.com/api/webhooks/123/secret"
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )
        session = FakeSession(error=requests.Timeout(f"POST {webhook_url} timed out"))
        notifier = WebhookNotifier(webhook_url, session=session)

        with self.assertRaises(RuntimeError) as exc_info:
            notifier.send(event)

        self.assertNotIn(webhook_url, str(exc_info.exception))
        self.assertIn("[REDACTED_WEBHOOK_URL]", str(exc_info.exception))

    def test_run_once_without_updates_only_logs_report(self):
        notifier = FakeNotifier()
        reports = []
        errors = []

        outcome = run_once(
            self.make_config(),
            notifier=notifier,
            checker=lambda _: {"updates": []},
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=errors.append,
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(0, outcome["notifiedUpdateCount"])
        self.assertEqual(0, outcome["suppressedUpdateCount"])
        self.assertEqual(0, outcome["errorCount"])
        self.assertEqual([], notifier.events)
        self.assertEqual(1, len(reports))
        self.assertIn("daily notification: 送信なし", reports[0])
        self.assertIn("通知対象: 0件", reports[0])
        self.assertIn("通知抑制: 0件", reports[0])
        self.assertIn("source failure: 0件", reports[0])
        self.assertIn("run-level failure: 0件", reports[0])
        self.assertIn("delivery failure: 0件", reports[0])
        self.assertEqual([], errors)

    def test_run_once_with_default_notify_update_sends_event_and_logs_report(self):
        notifier = FakeNotifier()
        reports = []

        outcome = run_once(
            self.make_config(),
            notifier=notifier,
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(1, outcome["notifiedUpdateCount"])
        self.assertEqual(0, outcome["suppressedUpdateCount"])
        self.assertEqual(1, len(notifier.events))
        payload = notifier.events[0].as_payload()
        self.assertEqual("work-1", payload["work_id"])
        self.assertEqual("episode-2", payload["latest_key"])
        self.assertEqual("作品A", payload["series_title"])
        self.assertEqual("main_story", payload["update_type"])
        self.assertEqual("2023-11-14T22:13:20Z", payload["detected_at"])
        self.assertTrue(payload["notification"]["should_notify"])
        self.assertIn("daily notification: 送信なし", reports[0])
        self.assertIn("通知対象: 1件", reports[0])
        self.assertIn("通知抑制: 0件", reports[0])

    def test_run_once_records_run_summary(self):
        recorded = []

        outcome = run_once(
            self.make_config(),
            notifier=FakeNotifier(),
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=self.make_state,
            state_saver=lambda _: None,
            run_recorder=recorded.append,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: None,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(1, len(recorded))
        self.assertEqual(outcome, recorded[0])

    def test_run_once_reports_failure_when_run_recorder_raises(self):
        reports = []
        errors = []

        outcome = run_once(
            self.make_config(),
            notifier=FakeNotifier(),
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=self.make_state,
            state_saver=lambda _: None,
            run_recorder=lambda _summary: (_ for _ in ()).throw(RuntimeError("firestore write failed")),
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=errors.append,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual([], reports)
        self.assertEqual(1, outcome["errorCount"])
        self.assertIn("record_run_summary", outcome["error"])
        self.assertEqual(1, len(errors))
        self.assertIn("巡回実行に失敗しました", errors[0])
        self.assertIn("record_run_summary", errors[0])

    def test_run_once_suppresses_bonus_updates_from_notifier_but_reports_them(self):
        notifier = FakeNotifier()
        reports = []

        outcome = run_once(
            self.make_config(),
            notifier=notifier,
            checker=lambda _: {
                "updates": [
                    self.make_update(
                        update_type="bonus",
                        default_notify=False,
                        episode_title="番外編",
                        classification_reason="episode_title matched bonus marker",
                    )
                ]
            },
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(0, outcome["notifiedUpdateCount"])
        self.assertEqual(1, outcome["suppressedUpdateCount"])
        self.assertEqual([], notifier.events)
        self.assertIn("更新検知: 1件", reports[0])
        self.assertIn("通知対象: 0件", reports[0])
        self.assertIn("通知抑制: 1件", reports[0])
        self.assertIn("daily notification: 送信なし", reports[0])

    def test_run_once_unknown_updates_fail_open_to_notifier(self):
        notifier = FakeNotifier()
        update = self.make_update(
            update_type="unknown",
            default_notify=True,
            episode_title="春の特別掲載",
            classification_reason="matched both story and bonus markers",
        )
        update.pop("notification")

        outcome = run_once(
            self.make_config(),
            notifier=notifier,
            checker=lambda _: {
                "updates": [update]
            },
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: None,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(1, len(notifier.events))
        payload = notifier.events[0].as_payload()
        self.assertEqual("unknown", payload["update_type"])
        self.assertEqual(
            "matched both story and bonus markers",
            payload["to"]["classification_reason"],
        )

    def test_run_once_mode_all_notifies_bonus_updates_even_when_default_notify_is_false(self):
        notifier = FakeNotifier()

        outcome = run_once(
            self.make_config(),
            notifier=notifier,
            checker=lambda _: {
                "updates": [
                    self.make_update(
                        update_type="bonus",
                        default_notify=False,
                        episode_title="番外編",
                        classification_reason="episode_title matched bonus marker",
                        notification=self.make_notification(
                            mode="all",
                            should_notify=True,
                            reason="mode=all notifies every update_type",
                        ),
                    )
                ]
            },
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: None,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(1, outcome["notifiedUpdateCount"])
        self.assertEqual(0, outcome["suppressedUpdateCount"])
        self.assertEqual(1, len(notifier.events))
        payload = notifier.events[0].as_payload()
        self.assertEqual("bonus", payload["update_type"])
        self.assertFalse(payload["to"]["default_notify"])
        self.assertEqual("all", payload["notification"]["mode"])
        self.assertTrue(payload["notification"]["should_notify"])

    def test_run_once_marks_source_errors_as_degraded_while_still_sending_events(self):
        notifier = FakeNotifier()
        reports = []
        errors = {
            "sources": [
                {
                    "id": "work-2",
                    "phase": "fetch_latest",
                    "kind": "parse",
                    "message": "parse failed",
                }
            ],
            "run": [],
        }
        state = self.make_state()
        state["works"]["work-2"] = {
            "latest": {"series_title": "作品B", "episode_title": "第5話"},
            "history": [],
            "health": {
                "last_checked_at": 1_700_000_000,
                "last_success_at": 1_700_000_000,
                "consecutive_failures": 1,
            },
        }

        outcome = run_once(
            self.make_config(),
            notifier=notifier,
            checker=lambda _: {"updates": [self.make_update()], "errors": errors},
            state_loader=lambda: state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(1, outcome["notifiedUpdateCount"])
        self.assertEqual(0, outcome["suppressedUpdateCount"])
        self.assertEqual(1, outcome["errorCount"])
        self.assertEqual(1, len(notifier.events))
        self.assertIn("巡回実行に一部失敗がありました", reports[0])
        self.assertIn("通知対象: 1件", reports[0])
        self.assertIn("source failure: 1件", reports[0])
        self.assertIn("source/parse [fetch_latest] work-2: parse failed", reports[0])

    def test_run_once_logs_failure_report_when_notifier_fails(self):
        notifier = FakeNotifier(fail_on_index=0)
        reports = []
        errors = []

        outcome = run_once(
            self.make_config(),
            notifier=notifier,
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=errors.append,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(1, outcome["updateCount"])
        self.assertEqual(1, outcome["notifiedUpdateCount"])
        self.assertEqual(0, outcome["suppressedUpdateCount"])
        self.assertEqual([], reports)
        self.assertEqual(1, len(errors))
        self.assertIn("巡回実行に失敗しました", errors[0])
        self.assertIn("notifier backend failed", errors[0])

    def test_run_once_continues_delivering_valid_updates_when_one_payload_is_invalid(self):
        notifier = FakeNotifier()
        errors = []
        invalid_update = self.make_update()
        invalid_update["to"] = {
            "series_title": "作品A",
            "episode_title": "第2話",
            "update_type": "main_story",
            "default_notify": True,
        }

        outcome = run_once(
            self.make_config(),
            notifier=notifier,
            checker=lambda _: {"updates": [invalid_update, self.make_update(latest_key="episode-3")]},
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: self.fail("unexpected report log"),
            error_logger=errors.append,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(2, outcome["notifiedUpdateCount"])
        self.assertEqual(1, len(notifier.events))
        self.assertEqual("episode-3", notifier.events[0].latest_key)
        self.assertEqual(1, len(errors))
        self.assertIn("work-1: update event work-1 is missing latest_key", errors[0])

    def test_build_update_event_requires_explicit_latest_key_without_fallback(self):
        invalid_update = self.make_update()
        invalid_update["to"] = {
            "series_title": "作品A",
            "episode_title": "第2話",
            "episode_code": "episode-2",
            "url": "https://example.com/2",
        }

        with self.assertRaisesRegex(ValueError, "update event work-1 is missing latest_key"):
            build_update_event(invalid_update, detected_at="2023-11-14T22:13:20Z")

    def test_run_once_persists_only_failed_backends_in_notification_outbox(self):
        stdout_notifier = FakeNotifier()
        webhook_notifier = FakeNotifier(fail_on_index=0)
        errors = []
        store, load_from_store, save_to_store = self.make_state_store()

        outcome = run_once(
            self.make_config(),
            named_notifiers={"stdout": stdout_notifier, "webhook": webhook_notifier},
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: None,
            error_logger=errors.append,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(1, len(stdout_notifier.events))
        self.assertEqual(0, len(webhook_notifier.events))
        self.assertEqual(1, len(store["notification_outbox"]))
        self.assertEqual(["webhook"], store["notification_outbox"][0]["pending_backends"])
        self.assertEqual(1, store["notification_outbox"][0]["attempt_count"])
        self.assertIn("webhook: notifier backend failed", store["notification_outbox"][0]["last_error"])
        self.assertEqual(1, len(errors))
        self.assertIn("notification delivery failed", errors[0])

    def test_run_once_replays_pending_notification_outbox_on_next_run(self):
        failing_notifier = FakeNotifier(fail_on_index=0)
        store, load_from_store, save_to_store = self.make_state_store()

        first_outcome = run_once(
            self.make_config(),
            named_notifiers={"stdout": failing_notifier},
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )

        self.assertFalse(first_outcome["ok"])
        self.assertEqual(1, len(store["notification_outbox"]))

        succeeding_notifier = FakeNotifier()
        reports = []
        second_outcome = run_once(
            self.make_config(),
            named_notifiers={"stdout": succeeding_notifier},
            checker=lambda _: {"updates": []},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_300,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(second_outcome["ok"])
        self.assertEqual(1, len(succeeding_notifier.events))
        self.assertEqual([], store["notification_outbox"])
        self.assertIn("daily notification: 送信なし", reports[0])
        self.assertIn("generic notifier outbox残件: 0件", reports[0])

    def test_run_once_with_discord_outbound_sends_daily_notification_and_run_report(self):
        notifier = FakeNotifier()
        discord = FakeDiscordClient()
        reports = []
        store, load_from_store, save_to_store = self.make_state_store()

        outcome = run_once(
            self.make_config(with_discord=True),
            notifier=notifier,
            discord_client=discord,
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertTrue(outcome["dailyNotificationSent"])
        self.assertEqual(1, len(notifier.events))
        self.assertEqual(["main-channel", "run-report-channel"], [call["channel_id"] for call in discord.calls])
        self.assertIn("新着エピソードを検知しました", discord.calls[0]["content"])
        self.assertIn("[作品A：第2話](<https://example.com/2>)←第1話", discord.calls[0]["content"])
        self.assertIn("daily notification: 送信した", discord.calls[1]["content"])
        self.assertEqual(
            "episode-2",
            store["discord_delivery"]["daily_notification"]["delivered_latest_keys"]["work-1"]["latest_key"],
        )
        self.assertEqual([], store["discord_delivery"]["daily_notification"]["pending_messages"])
        self.assertEqual(1, len(reports))
        self.assertIn("daily notification: 送信した", reports[0])

    def test_run_once_replays_pending_daily_notification_on_next_run(self):
        failing_discord = FakeDiscordClient(fail_channels={"main-channel"})
        store, load_from_store, save_to_store = self.make_state_store()
        errors = []

        first_outcome = run_once(
            self.make_config(with_discord=True),
            notifier=FakeNotifier(),
            discord_client=failing_discord,
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: self.fail("unexpected report log"),
            error_logger=errors.append,
        )

        self.assertFalse(first_outcome["ok"])
        self.assertFalse(first_outcome["dailyNotificationSent"])
        self.assertEqual(1, len(store["discord_delivery"]["daily_notification"]["pending_messages"]))
        self.assertEqual({}, store["discord_delivery"]["daily_notification"]["delivered_latest_keys"])
        self.assertEqual(1, len(errors))
        self.assertIn("notification delivery failed", errors[0])

        succeeding_discord = FakeDiscordClient()
        reports = []
        second_outcome = run_once(
            self.make_config(with_discord=True),
            notifier=FakeNotifier(),
            discord_client=succeeding_discord,
            checker=lambda _: {"updates": []},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_300,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(second_outcome["ok"])
        self.assertTrue(second_outcome["dailyNotificationSent"])
        self.assertEqual(["main-channel", "run-report-channel"], [call["channel_id"] for call in succeeding_discord.calls])
        self.assertEqual([], store["discord_delivery"]["daily_notification"]["pending_messages"])
        self.assertEqual(
            "episode-2",
            store["discord_delivery"]["daily_notification"]["delivered_latest_keys"]["work-1"]["latest_key"],
        )
        self.assertIn("daily notification: 送信した", reports[0])

    def test_run_once_reports_daily_pending_and_delivery_failure_visibility(self):
        store, load_from_store, save_to_store = self.make_state_store(
            {
                **self.make_state(),
                "discord_delivery": {
                    "daily_notification": {
                        "delivered_latest_keys": {},
                        "pending_messages": [
                            {
                                "channel_id": "main-channel",
                                "content": "pending message",
                                "message_keys": [{"work_id": "work-1", "latest_key": "episode-2"}],
                                "created_at": "2023-11-14T22:13:20Z",
                                "attempt_count": 1,
                                "last_attempted_at": "2023-11-14T22:14:00Z",
                                "last_error": "discord delivery failed for main-channel",
                            }
                        ],
                    }
                },
            }
        )
        discord = FakeDiscordClient(fail_channels={"main-channel"})
        errors = []

        outcome = run_once(
            self.make_config(with_discord=True),
            notifier=FakeNotifier(),
            discord_client=discord,
            checker=lambda _: {"updates": []},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_300,
            report_logger=lambda _: self.fail("unexpected report log"),
            error_logger=errors.append,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(["main-channel", "run-report-channel"], [call["channel_id"] for call in discord.calls])
        self.assertIn("Discord daily pending: 1件", discord.calls[1]["content"])
        self.assertIn("delivery failure: 1件", discord.calls[1]["content"])
        self.assertIn("generic notifier outbox残件: 0件", discord.calls[1]["content"])
        self.assertEqual(1, len(store["discord_delivery"]["daily_notification"]["pending_messages"]))
        self.assertEqual(1, len(errors))
        self.assertIn("notification delivery failed", errors[0])

    def test_run_once_clears_pending_daily_notification_if_message_is_already_visible(self):
        pending_content = "pending message"
        store, load_from_store, save_to_store = self.make_state_store(
            {
                **self.make_state(),
                "discord_delivery": {
                    "daily_notification": {
                        "delivered_latest_keys": {},
                        "pending_messages": [
                            {
                                "channel_id": "main-channel",
                                "content": pending_content,
                                "message_keys": [{"work_id": "work-1", "latest_key": "episode-2"}],
                                "created_at": "2023-11-14T22:13:20Z",
                                "attempt_count": 1,
                                "last_attempted_at": "2023-11-14T22:14:00Z",
                                "last_error": "discord delivery failed",
                            }
                        ],
                    }
                },
            }
        )
        discord = FakeDiscordClient(
            channel_messages={
                "main-channel": [
                    {
                        "id": "42",
                        "content": pending_content,
                        "author": {"id": "bot-user"},
                    }
                ]
            }
        )
        reports = []

        outcome = run_once(
            self.make_config(with_discord=True),
            notifier=FakeNotifier(),
            discord_client=discord,
            checker=lambda _: {"updates": []},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_300,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertTrue(outcome["dailyNotificationSent"])
        self.assertEqual(["run-report-channel"], [call["channel_id"] for call in discord.calls])
        self.assertEqual([], store["discord_delivery"]["daily_notification"]["pending_messages"])
        self.assertEqual(
            "episode-2",
            store["discord_delivery"]["daily_notification"]["delivered_latest_keys"]["work-1"]["latest_key"],
        )
        self.assertEqual(1, len(reports))
        self.assertIn("daily notification: 送信した", reports[0])

    def test_run_once_logs_secondary_failure_when_run_report_delivery_fails(self):
        discord = FakeDiscordClient(fail_channels={"run-report-channel"})
        errors = []

        outcome = run_once(
            self.make_config(with_discord=True),
            notifier=FakeNotifier(),
            discord_client=discord,
            checker=lambda _: {"updates": []},
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: self.fail("unexpected report log"),
            error_logger=errors.append,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(1, len(discord.calls))
        self.assertEqual("run-report-channel", discord.calls[0]["channel_id"])
        self.assertEqual(1, len(errors))
        self.assertIn("run report 自体の送信に失敗しました", errors[0])
        self.assertIn("トリガー: scheduled", errors[0])

    def test_run_once_sends_run_report_to_discord_when_checker_raises(self):
        discord = FakeDiscordClient()
        errors = []

        outcome = run_once(
            self.make_config(with_discord=True),
            notifier=FakeNotifier(),
            discord_client=discord,
            checker=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: self.fail("unexpected report log"),
            error_logger=errors.append,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(1, len(discord.calls))
        self.assertEqual("run-report-channel", discord.calls[0]["channel_id"])
        self.assertIn("run-level failure: 1件", discord.calls[0]["content"])
        self.assertIn("boom", discord.calls[0]["content"])
        self.assertEqual(1, len(errors))
        self.assertIn("boom", errors[0])

    def test_run_once_redacts_secrets_from_failure_outputs(self):
        bot_token = "discord-bot-token"
        webhook_url = "https://discord.com/api/webhooks/123/secret"
        discord = SecretLeakingDiscordClient(bot_token)
        errors = []
        store, load_from_store, save_to_store = self.make_state_store()
        config = RunnerConfig(
            timezone_name="Asia/Tokyo",
            watchlist_path="/tmp/watchlist.json",
            crawl_schedule="0 19 * * *",
            crawl_interval=None,
            run_on_startup=True,
            notifier_config=NotifierConfig(backends=("webhook",), webhook_url=webhook_url),
            discord_outbound_config=DiscordOutboundConfig(
                bot_token=bot_token,
                main_channel_id="main-channel",
                run_report_channel_id="run-report-channel",
            ),
        )

        outcome = run_once(
            config,
            named_notifiers={"webhook": SecretLeakingNotifier(f"webhook delivery failed for {webhook_url}")},
            discord_client=discord,
            checker=lambda _: {"updates": [self.make_update()]},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: self.fail("unexpected report log"),
            error_logger=errors.append,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(2, len(discord.calls))
        run_report = discord.calls[1]["content"]
        self.assertNotIn(bot_token, run_report)
        self.assertNotIn(webhook_url, run_report)
        self.assertIn("[REDACTED_BOT_TOKEN]", run_report)
        self.assertIn("[REDACTED_WEBHOOK_URL]", run_report)
        self.assertEqual(1, len(errors))
        self.assertNotIn(bot_token, errors[0])
        self.assertNotIn(webhook_url, errors[0])
        self.assertIn("[REDACTED_BOT_TOKEN]", errors[0])
        self.assertIn("[REDACTED_WEBHOOK_URL]", errors[0])
        self.assertNotIn(webhook_url, store["notification_outbox"][0]["last_error"])
        self.assertIn("[REDACTED_WEBHOOK_URL]", store["notification_outbox"][0]["last_error"])
        self.assertNotIn(
            bot_token,
            store["discord_delivery"]["daily_notification"]["pending_messages"][0]["last_error"],
        )
        self.assertIn(
            "[REDACTED_BOT_TOKEN]",
            store["discord_delivery"]["daily_notification"]["pending_messages"][0]["last_error"],
        )

    def test_handle_fetch_trigger_accepts_when_idle_and_runs_in_background(self):
        checker_started = threading.Event()
        allow_finish = threading.Event()
        notifier = FakeNotifier()
        reports = []

        def checker(_):
            checker_started.set()
            allow_finish.wait(1.0)
            return {"updates": []}

        coordinator = RunCoordinator(
            self.make_config(),
            notifier=notifier,
            checker=checker,
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        outcome = start_fetch_run(coordinator)

        self.assertTrue(outcome["ok"])
        self.assertTrue(outcome["accepted"])
        self.assertTrue(outcome["background"])
        self.assertEqual(TRIGGER_SOURCE_DISCORD_FETCH, outcome["triggerSource"])
        self.assertEqual(FETCH_ACCEPTED_MESSAGE, outcome["message"])
        self.assertTrue(checker_started.wait(0.5))
        self.assertTrue(coordinator.is_running())

        allow_finish.set()
        self.wait_until(lambda: not coordinator.is_running())
        self.assertEqual(1, len(reports))
        self.assertEqual([], notifier.events)

    def test_run_coordinator_queues_startup_while_fetch_is_in_progress(self):
        checker_started = threading.Event()
        allow_finish = threading.Event()
        reports = []
        call_count = {"value": 0}

        def checker(_):
            call_count["value"] += 1
            if call_count["value"] == 1:
                checker_started.set()
                allow_finish.wait(1.0)
            return {"updates": []}

        coordinator = RunCoordinator(
            self.make_config(),
            notifier=FakeNotifier(),
            checker=checker,
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        fetch_outcome = start_fetch_run(coordinator)
        self.assertTrue(fetch_outcome["accepted"])
        self.assertTrue(checker_started.wait(0.5))

        startup_outcome = coordinator.run(TRIGGER_SOURCE_STARTUP)

        self.assertTrue(startup_outcome["ok"])
        self.assertTrue(startup_outcome["accepted"])
        self.assertTrue(startup_outcome["queued"])
        self.assertTrue(startup_outcome["serialized"])
        self.assertEqual(TRIGGER_SOURCE_STARTUP, startup_outcome["triggerSource"])

        allow_finish.set()
        self.wait_until(lambda: not coordinator.is_running())
        self.assertEqual(2, call_count["value"])
        self.assertEqual(2, len(reports))
        self.assertIn("トリガー: startup", reports[1])

    def test_run_coordinator_queues_scheduled_while_fetch_is_in_progress(self):
        checker_started = threading.Event()
        allow_finish = threading.Event()
        reports = []
        call_count = {"value": 0}

        def checker(_):
            call_count["value"] += 1
            if call_count["value"] == 1:
                checker_started.set()
                allow_finish.wait(1.0)
            return {"updates": []}

        coordinator = RunCoordinator(
            self.make_config(),
            notifier=FakeNotifier(),
            checker=checker,
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        fetch_outcome = start_fetch_run(coordinator)
        self.assertTrue(fetch_outcome["accepted"])
        self.assertTrue(checker_started.wait(0.5))

        scheduled_outcome = coordinator.run(TRIGGER_SOURCE_SCHEDULED)

        self.assertTrue(scheduled_outcome["ok"])
        self.assertTrue(scheduled_outcome["accepted"])
        self.assertTrue(scheduled_outcome["queued"])
        self.assertTrue(scheduled_outcome["serialized"])
        self.assertEqual(TRIGGER_SOURCE_SCHEDULED, scheduled_outcome["triggerSource"])

        allow_finish.set()
        self.wait_until(lambda: not coordinator.is_running())
        self.assertEqual(2, call_count["value"])
        self.assertEqual(2, len(reports))
        self.assertIn("トリガー: scheduled", reports[1])

    def test_handle_fetch_trigger_accepts_again_after_failure(self):
        call_count = {"value": 0}
        reports = []
        errors = []

        def checker(_):
            call_count["value"] += 1
            if call_count["value"] == 1:
                raise RuntimeError("boom")
            return {"updates": []}

        coordinator = RunCoordinator(
            self.make_config(),
            notifier=FakeNotifier(),
            checker=checker,
            state_loader=self.make_state,
            state_saver=lambda _: None,
            now_fn=lambda: 1_700_000_000 + call_count["value"],
            report_logger=reports.append,
            error_logger=errors.append,
        )

        first_outcome = start_fetch_run(coordinator)
        self.assertTrue(first_outcome["accepted"])
        self.wait_until(lambda: not coordinator.is_running())

        second_outcome = start_fetch_run(coordinator)
        self.assertTrue(second_outcome["accepted"])
        self.wait_until(lambda: not coordinator.is_running())

        self.assertEqual(2, call_count["value"])
        self.assertEqual(1, len(errors))
        self.assertIn("トリガー: discord_fetch", errors[0])
        self.assertIn("boom", errors[0])
        self.assertEqual(1, len(reports))

    def test_queued_fetch_defers_second_run_until_current_run_finishes(self):
        checker_started = threading.Event()
        allow_finish = threading.Event()
        calls = {"checker": 0, "state_loader": 0, "state_saver": 0}
        notifier = FakeNotifier()

        def checker(_):
            calls["checker"] += 1
            checker_started.set()
            allow_finish.wait(1.0)
            return {"updates": []}

        def state_loader():
            calls["state_loader"] += 1
            return self.make_state()

        def state_saver(_):
            calls["state_saver"] += 1

        coordinator = RunCoordinator(
            self.make_config(),
            notifier=notifier,
            checker=checker,
            state_loader=state_loader,
            state_saver=state_saver,
            now_fn=lambda: 1_700_000_000,
            report_logger=lambda _: None,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        accepted_outcome = start_fetch_run(coordinator)
        self.assertTrue(accepted_outcome["accepted"])
        self.assertTrue(checker_started.wait(0.5))

        queued_outcome = start_fetch_run(coordinator)

        self.assertTrue(queued_outcome["ok"])
        self.assertTrue(queued_outcome["accepted"])
        self.assertTrue(queued_outcome["queued"])
        self.assertTrue(queued_outcome["serialized"])
        self.assertEqual(FETCH_ACCEPTED_MESSAGE, queued_outcome["message"])
        self.assertEqual(1, calls["checker"])
        self.assertEqual(0, calls["state_loader"])
        self.assertEqual(0, calls["state_saver"])
        self.assertEqual([], notifier.events)

        allow_finish.set()
        self.wait_until(lambda: not coordinator.is_running())
        self.assertEqual(2, calls["checker"])

    def test_replay_outbox_once_delivers_pending_events_and_clears_outbox(self):
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )
        store, load_from_store, save_to_store = self.make_state_store(
            {
                **self.make_state(),
                "notification_outbox": [
                    {
                        "event": event.as_payload(),
                        "pending_backends": ["stdout"],
                        "attempt_count": 1,
                        "last_attempted_at": "2023-11-14T22:13:20Z",
                        "last_error": "stdout: timed out",
                    }
                ],
            }
        )
        notifier = FakeNotifier()
        reports = []

        outcome = replay_outbox_once(
            self.make_config(),
            named_notifiers={"stdout": notifier},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_300,
            report_logger=reports.append,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(1, len(notifier.events))
        self.assertEqual([], store["notification_outbox"])
        self.assertIn("再送対象: 1件", reports[0])
        self.assertIn("再送残件: 0件", reports[0])

    def test_replay_outbox_once_keeps_discord_daily_pending_messages_untouched(self):
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )
        store, load_from_store, save_to_store = self.make_state_store(
            {
                **self.make_state(),
                "notification_outbox": [
                    {
                        "event": event.as_payload(),
                        "pending_backends": ["stdout"],
                        "attempt_count": 1,
                        "last_attempted_at": "2023-11-14T22:13:20Z",
                        "last_error": "stdout: timed out",
                    }
                ],
                "discord_delivery": {
                    "daily_notification": {
                        "delivered_latest_keys": {},
                        "pending_messages": [
                            {
                                "channel_id": "main-channel",
                                "content": "pending daily message",
                                "message_keys": [{"work_id": "work-1", "latest_key": "episode-2"}],
                                "created_at": "2023-11-14T22:13:20Z",
                                "attempt_count": 1,
                                "last_attempted_at": "2023-11-14T22:14:00Z",
                                "last_error": "discord delivery failed for main-channel",
                            }
                        ],
                    }
                },
            }
        )
        notifier = FakeNotifier()

        outcome = replay_outbox_once(
            self.make_config(),
            named_notifiers={"stdout": notifier},
            state_loader=load_from_store,
            state_saver=save_to_store,
            now_fn=lambda: 1_700_000_300,
            report_logger=lambda _: None,
            error_logger=lambda _: self.fail("unexpected error log"),
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(1, len(notifier.events))
        self.assertEqual([], store["notification_outbox"])
        self.assertEqual(
            1,
            len(store["discord_delivery"]["daily_notification"]["pending_messages"]),
        )
        self.assertEqual(
            "episode-2",
            store["discord_delivery"]["daily_notification"]["pending_messages"][0]["message_keys"][0]["latest_key"],
        )

    def test_replay_outbox_module_replays_pending_events(self):
        repo_root = Path(__file__).resolve().parents[1]
        event = build_update_event(
            self.make_update(latest_key="episode-2"),
            detected_at="2023-11-14T22:13:20Z",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            save_state(
                {
                    **self.make_state(),
                    "notification_outbox": [
                        {
                            "event": event.as_payload(),
                            "pending_backends": ["stdout"],
                            "attempt_count": 1,
                            "last_attempted_at": "2023-11-14T22:13:20Z",
                            "last_error": "stdout: timed out",
                        }
                    ],
                },
                path=str(state_path),
            )
            env = os.environ.copy()
            env["MANGA_WATCH_STATE"] = str(state_path)
            env["MANGA_WATCH_NOTIFIER_BACKENDS"] = "stdout"
            env.pop("MANGA_WATCH_WEBHOOK_URL", None)

            result = subprocess.run(
                [sys.executable, "-m", "manga_watch.replay_outbox"],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode)
            self.assertIn(event.event_id, result.stdout)
            self.assertEqual([], load_state(str(state_path))["notification_outbox"])


if __name__ == "__main__":
    unittest.main()
