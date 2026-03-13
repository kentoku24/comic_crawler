import tempfile
import unittest
from pathlib import Path

import requests

from manga_watch.discord_outbound import (
    DiscordChannelClient,
    DiscordOutboundConfig,
    build_daily_notification_message,
    enqueue_daily_notification,
)
from manga_watch.storage import load_state, save_state


class FakeResponse:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, responses=None, get_responses=None, put_responses=None, error=None):
        self.responses = list(responses or [])
        self.get_responses = list(get_responses or [])
        self.put_responses = list(put_responses or [])
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

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=None):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        if self.error is not None:
            raise self.error
        if not self.get_responses:
            raise AssertionError("unexpected discord read request")
        return self.get_responses.pop(0)

    def put(self, url, headers=None, timeout=None, allow_redirects=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        if self.error is not None:
            raise self.error
        if not self.put_responses:
            raise AssertionError("unexpected discord reaction request")
        return self.put_responses.pop(0)


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

    def test_enqueue_daily_notification_skips_updates_without_latest_key(self):
        state = {
            "discord_delivery": {
                "daily_notification": {
                    "delivered_latest_keys": {},
                    "pending_messages": [],
                }
            }
        }
        update = {
            "id": "work-1",
            "from": {
                "seriesTitle": "作品A",
                "episodeTitle": "第1話",
                "latestKey": "episode-1",
            },
            "to": {
                "series_title": "作品A",
                "episode_title": "第2話 改題",
                "episode_code": "episode-2",
                "url": "https://example.com/latest",
            },
        }

        result = enqueue_daily_notification(
            state,
            updates=[update],
            channel_id="main-channel",
            now_ts=1_700_000_000,
            timezone_name="Asia/Tokyo",
            created_at="2023-11-14T22:13:20Z",
        )

        self.assertEqual({"queued": False, "candidateUpdateCount": 0}, result)
        self.assertEqual([], state["discord_delivery"]["daily_notification"]["pending_messages"])

    def test_enqueue_daily_notification_dedupes_by_work_id_and_latest_key_even_if_metadata_changes(self):
        state = {
            "discord_delivery": {
                "daily_notification": {
                    "delivered_latest_keys": {
                        "work-1": {
                            "latest_key": "episode-2",
                            "delivered_at": "2023-11-14T22:13:20Z",
                        }
                    },
                    "pending_messages": [],
                }
            }
        }

        result = enqueue_daily_notification(
            state,
            updates=[
                self.make_update(
                    episode_title="第2話 改題",
                    previous="第2話",
                )
            ],
            channel_id="main-channel",
            now_ts=1_700_000_300,
            timezone_name="Asia/Tokyo",
            created_at="2023-11-14T22:18:20Z",
        )

        self.assertEqual({"queued": False, "candidateUpdateCount": 0}, result)
        self.assertEqual([], state["discord_delivery"]["daily_notification"]["pending_messages"])

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

    def test_discord_channel_client_reads_current_user_and_channel_messages(self):
        session = FakeSession(
            get_responses=[
                FakeResponse(200, json_data={"id": "bot-user"}),
                FakeResponse(
                    200,
                    json_data=[
                        {"id": "11", "content": "latest", "author": {"id": "user-1"}},
                    ],
                ),
            ]
        )
        client = DiscordChannelClient(
            DiscordOutboundConfig(
                bot_token="discord-bot-token",
                main_channel_id="main-channel",
                run_report_channel_id="run-report-channel",
            ),
            session=session,
        )

        self.assertEqual("bot-user", client.get_current_user_id())
        messages = client.list_channel_messages("main-channel", after="10", limit=100)

        self.assertEqual(
            "https://discord.com/api/v10/users/@me",
            session.calls[0]["url"],
        )
        self.assertEqual(
            "https://discord.com/api/v10/channels/main-channel/messages",
            session.calls[1]["url"],
        )
        self.assertEqual({"limit": 100, "after": "10"}, session.calls[1]["params"])
        self.assertEqual("latest", messages[0]["content"])

    def test_discord_channel_client_add_reaction_uses_reactions_endpoint(self):
        session = FakeSession(put_responses=[FakeResponse(204)])
        client = DiscordChannelClient(
            DiscordOutboundConfig(
                bot_token="discord-bot-token",
                main_channel_id="main-channel",
                run_report_channel_id="run-report-channel",
            ),
            session=session,
        )

        client.add_reaction("main-channel", "123", "✅")

        self.assertEqual(
            "https://discord.com/api/v10/channels/main-channel/messages/123/reactions/%E2%9C%85/@me",
            session.calls[0]["url"],
        )
        self.assertEqual("Bot discord-bot-token", session.calls[0]["headers"]["Authorization"])

    def test_discord_channel_client_masks_bot_token_in_transport_error(self):
        token = "discord-bot-token"
        session = FakeSession(error=requests.Timeout(f"Authorization: Bot {token}"))
        client = DiscordChannelClient(
            DiscordOutboundConfig(
                bot_token=token,
                main_channel_id="main-channel",
                run_report_channel_id="run-report-channel",
            ),
            session=session,
        )

        with self.assertRaises(RuntimeError) as exc_info:
            client.send_message("run-report-channel", "hello")

        self.assertNotIn(token, str(exc_info.exception))
        self.assertIn("[REDACTED_BOT_TOKEN]", str(exc_info.exception))

    def test_discord_channel_client_masks_bot_token_in_error_response(self):
        token = "discord-bot-token"
        session = FakeSession(
            responses=[FakeResponse(401, text=f"Authorization header was Bot {token}")]
        )
        client = DiscordChannelClient(
            DiscordOutboundConfig(
                bot_token=token,
                main_channel_id="main-channel",
                run_report_channel_id="run-report-channel",
            ),
            session=session,
        )

        with self.assertRaises(RuntimeError) as exc_info:
            client.send_message("run-report-channel", "hello")

        self.assertNotIn(token, str(exc_info.exception))
        self.assertIn("[REDACTED_BOT_TOKEN]", str(exc_info.exception))

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
