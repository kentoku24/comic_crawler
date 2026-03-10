from __future__ import annotations

import unittest

from manga_watch.discord_outbound import DiscordOutboundConfig
from manga_watch.discord_real_e2e import (
    DiscordE2ECase,
    build_representative_cases,
    run_case,
    select_cases,
    verify_message,
)


class FakeDiscordE2EClient:
    def __init__(self):
        self.bot_user_id = "bot-user"
        self.sent_messages = []
        self.channel_messages = {
            "main-channel": [
                {"id": "10", "content": "older", "author": {"id": "bot-user", "bot": True}},
            ],
            "run-report-channel": [],
        }

    def get_current_user_id(self) -> str:
        return self.bot_user_id

    def list_channel_messages(self, channel_id, *, after=None, limit=50):
        messages = list(self.channel_messages.get(channel_id, []))
        if after is not None:
            messages = [message for message in messages if int(str(message["id"])) > int(str(after))]
        return list(reversed(messages[-limit:]))

    def send_message(self, channel_id, content):
        self.sent_messages.append({"channel_id": channel_id, "content": content})
        next_id = str(sum(len(messages) for messages in self.channel_messages.values()) + 11)
        self.channel_messages.setdefault(channel_id, []).append(
            {
                "id": next_id,
                "content": content,
                "author": {"id": self.bot_user_id, "bot": True},
                "mention_everyone": False,
                "mentions": [],
                "mention_roles": [],
            }
        )


class DiscordRealE2ETests(unittest.TestCase):
    def make_config(self) -> DiscordOutboundConfig:
        return DiscordOutboundConfig(
            bot_token="discord-bot-token",
            main_channel_id="main-channel",
            run_report_channel_id="run-report-channel",
        )

    def test_build_representative_cases_cover_expected_surfaces(self):
        cases = build_representative_cases(self.make_config(), timezone_name="Asia/Tokyo")

        self.assertEqual(["latest", "daily", "run-report"], [case.name for case in cases])
        self.assertEqual(["main-channel", "main-channel", "run-report-channel"], [case.channel_id for case in cases])
        self.assertIn("保存済みの最新話一覧です", cases[0].content)
        self.assertIn("新着エピソードを検知しました", cases[1].content)
        self.assertIn("巡回実行しました", cases[2].content)

    def test_select_cases_returns_single_case_or_all(self):
        cases = build_representative_cases(self.make_config(), timezone_name="Asia/Tokyo")

        self.assertEqual(["daily"], [case.name for case in select_cases(cases, "daily")])
        self.assertEqual(3, len(select_cases(cases, "all")))

    def test_run_case_posts_and_verifies_message(self):
        client = FakeDiscordE2EClient()
        case = DiscordE2ECase(
            name="latest",
            channel_id="main-channel",
            description="latest",
            content="保存済みの最新話一覧です\n現在のリスト:",
        )

        result = run_case(
            client,
            case,
            timeout_seconds=0.01,
            poll_interval_seconds=0.0,
        )

        self.assertEqual("latest", result.name)
        self.assertEqual("main-channel", client.sent_messages[0]["channel_id"])
        self.assertTrue(result.content_matches)
        self.assertTrue(result.mentions_ok)

    def test_run_case_raises_when_message_never_appears(self):
        class NeverEchoClient(FakeDiscordE2EClient):
            def send_message(self, channel_id, content):
                self.sent_messages.append({"channel_id": channel_id, "content": content})

        client = NeverEchoClient()
        case = DiscordE2ECase(
            name="run-report",
            channel_id="run-report-channel",
            description="run-report",
            content="巡回実行しました",
        )

        with self.assertRaisesRegex(RuntimeError, "timed out"):
            run_case(
                client,
                case,
                timeout_seconds=0.01,
                poll_interval_seconds=0.0,
            )

    def test_verify_message_rejects_mentions(self):
        case = DiscordE2ECase(
            name="daily",
            channel_id="main-channel",
            description="daily",
            content="hello",
        )

        with self.assertRaisesRegex(RuntimeError, "unexpected @everyone mention"):
            verify_message(
                case,
                {
                    "id": "11",
                    "content": "hello",
                    "mention_everyone": True,
                    "mentions": [],
                    "mention_roles": [],
                },
            )


if __name__ == "__main__":
    unittest.main()
