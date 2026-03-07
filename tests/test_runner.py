import os
import subprocess
import sys
import unittest
from pathlib import Path

from manga_watch.runner import RunnerConfig, run_once, split_message


class FakeMessenger:
    def __init__(self, fail_on_channel=None):
        self.fail_on_channel = fail_on_channel
        self.messages = []

    def send_message(self, channel_id, content):
        if channel_id == self.fail_on_channel:
            raise RuntimeError("discord api error 500")
        self.messages.append((channel_id, content))


class RunnerTests(unittest.TestCase):
    def test_runner_module_runs_until_config_validation(self):
        repo_root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, "-m", "manga_watch.runner"],
            cwd=repo_root,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("[runner] configuration error:", result.stderr)

    def make_config(self):
        return RunnerConfig(
            discord_bot_token="token",
            discord_main_channel_id="main",
            discord_run_report_channel_id="report",
            timezone_name="Asia/Tokyo",
            urls_path="/tmp/urls.txt",
            crawl_schedule="0 19 * * *",
            crawl_interval=None,
            run_on_startup=True,
            request_timeout=30,
        )

    def test_run_once_without_updates_only_sends_report(self):
        messenger = FakeMessenger()
        state = {
            "items": {
                "work-1": {
                    "latest": {"seriesTitle": "作品A", "episodeTitle": "第1話"},
                }
            }
        }

        outcome = run_once(
            self.make_config(),
            messenger=messenger,
            checker=lambda _: {"updates": []},
            state_loader=lambda: state,
            now_fn=lambda: 1_700_000_000,
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(1, len(messenger.messages))
        self.assertEqual("report", messenger.messages[0][0])
        self.assertIn("通知: 送信なし", messenger.messages[0][1])
        self.assertIn("作品A：第1話", messenger.messages[0][1])

    def test_run_once_with_updates_sends_main_then_report(self):
        messenger = FakeMessenger()
        updates = [
            {
                "id": "work-1",
                "from": {"seriesTitle": "作品A", "episodeTitle": "第1話"},
                "to": {
                    "seriesTitle": "作品A",
                    "episodeTitle": "第2話",
                    "url": "https://example.com/2",
                },
            }
        ]
        state = {
            "items": {
                "work-1": {
                    "latest": {"seriesTitle": "作品A", "episodeTitle": "第2話"},
                }
            }
        }

        outcome = run_once(
            self.make_config(),
            messenger=messenger,
            checker=lambda _: {"updates": updates},
            state_loader=lambda: state,
            now_fn=lambda: 1_700_000_000,
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual("main", messenger.messages[0][0])
        self.assertIn("作品A：第1話 → 第2話", messenger.messages[0][1])
        self.assertEqual("report", messenger.messages[1][0])
        self.assertIn("通知: 送信した", messenger.messages[1][1])

    def test_run_once_sends_failure_report_when_notification_fails(self):
        messenger = FakeMessenger(fail_on_channel="main")
        state = {
            "items": {
                "work-1": {
                    "latest": {"seriesTitle": "作品A", "episodeTitle": "第2話"},
                }
            }
        }
        updates = [
            {
                "id": "work-1",
                "from": {"seriesTitle": "作品A", "episodeTitle": "第1話"},
                "to": {
                    "seriesTitle": "作品A",
                    "episodeTitle": "第2話",
                    "url": "https://example.com/2",
                },
            }
        ]

        outcome = run_once(
            self.make_config(),
            messenger=messenger,
            checker=lambda _: {"updates": updates},
            state_loader=lambda: state,
            now_fn=lambda: 1_700_000_000,
        )

        self.assertFalse(outcome["ok"])
        self.assertEqual(1, len(messenger.messages))
        self.assertEqual("report", messenger.messages[0][0])
        self.assertIn("巡回実行に失敗しました", messenger.messages[0][1])

    def test_split_message_splits_long_content(self):
        chunks = split_message("a" * 2100, limit=2000)
        self.assertEqual(2, len(chunks))
        self.assertEqual(2000, len(chunks[0]))
        self.assertEqual(100, len(chunks[1]))


if __name__ == "__main__":
    unittest.main()
