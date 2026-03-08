import tempfile
import unittest
from pathlib import Path

from manga_watch.discord_outbound import (
    DiscordChannelClient,
    DiscordOutboundConfig,
    build_daily_notification_message,
)
from manga_watch.storage import load_state, save_state


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None, allow_redirects=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected discord request")
        return self.responses.pop(0)


class DiscordOutboundTests(unittest.TestCase):
    def make_update(self, *, series="作品A", latest_key="episode-2", episode_title="第2話", previous="第1話"):
        return {
            "id": "work-1",
            "from": {
                "seriesTitle": series,
                "episodeTitle": previous,
                "latestKey": "episode-1",
            },
            "to": {
                "series_title": series,
                "episode_title": episode_title,
                "latest_key": latest_key,
                "url": "https://example.com/latest",
            },
        }

    def test_build_daily_notification_message_formats_lines_and_truncates_labels(self):
        message = build_daily_notification_message(
            [
                self.make_update(episode_title="第71話 abcdefghijk"),
                self.make_update(series="作品B", latest_key="episode-3", episode_title="第3話", previous="第2話"),
            ],
            now_ts=1_700_000_000,
            timezone_name="Asia/Tokyo",
        )

        lines = message.splitlines()
        self.assertEqual("新着エピソードを検知しました（2023-11-15）", lines[0])
        self.assertEqual("[作品A：第71話 abcdefg…](<https://example.com/latest>)←第1話", lines[1])
        self.assertEqual("[作品B：第3話](<https://example.com/latest>)←第2話", lines[2])

    def test_discord_channel_client_posts_bot_message(self):
        session = FakeSession(responses=[FakeResponse(200)])
        client = DiscordChannelClient(
            DiscordOutboundConfig(
                bot_token="discord-bot-token",
                main_channel_id="main-channel",
                run_report_channel_id="run-report-channel",
            ),
            session=session,
        )

        client.send_message("run-report-channel", "hello")

        self.assertEqual(1, len(session.calls))
        self.assertEqual(
            "https://discord.com/api/v10/channels/run-report-channel/messages",
            session.calls[0]["url"],
        )
        self.assertEqual("Bot discord-bot-token", session.calls[0]["headers"]["Authorization"])
        self.assertEqual({"content": "hello", "allowed_mentions": {"parse": []}}, session.calls[0]["json"])
        self.assertEqual(10, session.calls[0]["timeout"])
        self.assertFalse(session.calls[0]["allow_redirects"])

    def test_state_round_trip_preserves_discord_delivery_state(self):
        state = {
            "version": 2,
            "works": {},
            "last_run_at": 1_700_000_000,
            "notification_outbox": [],
            "discord_delivery": {
                "daily_notification": {
                    "delivered_latest_keys": {
                        "work-1": {
                            "latest_key": "episode-2",
                            "delivered_at": "2023-11-14T22:13:20Z",
                        }
                    },
                    "pending_messages": [
                        {
                            "channel_id": "main-channel",
                            "content": "pending message",
                            "message_keys": [{"work_id": "work-2", "latest_key": "episode-9"}],
                            "created_at": "2023-11-14T22:13:20Z",
                            "attempt_count": 1,
                            "last_attempted_at": "2023-11-14T22:14:00Z",
                            "last_error": "discord delivery failed",
                        }
                    ],
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            save_state(state, path=str(state_path))
            loaded = load_state(str(state_path))

        self.assertEqual(
            "episode-2",
            loaded["discord_delivery"]["daily_notification"]["delivered_latest_keys"]["work-1"]["latest_key"],
        )
        self.assertEqual(
            "main-channel",
            loaded["discord_delivery"]["daily_notification"]["pending_messages"][0]["channel_id"],
        )
        self.assertEqual(
            "episode-9",
            loaded["discord_delivery"]["daily_notification"]["pending_messages"][0]["message_keys"][0]["latest_key"],
        )


if __name__ == "__main__":
    unittest.main()
