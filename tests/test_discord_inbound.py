import unittest

from manga_watch.discord_inbound import DiscordCommandListener, split_discord_message
from manga_watch.runner import FETCH_ACCEPTED_MESSAGE


class FakeDiscordClient:
    def __init__(self, *, current_user_id="bot-user", polls=None):
        self.current_user_id = current_user_id
        self.polls = list(polls or [])
        self.list_calls = []
        self.sent_messages = []

    def get_current_user_id(self):
        return self.current_user_id

    def list_channel_messages(self, channel_id, *, after=None, limit=50):
        self.list_calls.append(
            {
                "channel_id": channel_id,
                "after": after,
                "limit": limit,
            }
        )
        if not self.polls:
            return []
        return self.polls.pop(0)

    def send_message(self, channel_id, content):
        self.sent_messages.append(
            {
                "channel_id": channel_id,
                "content": content,
            }
        )


class DiscordInboundTests(unittest.TestCase):
    def test_listener_handles_latest_query_after_priming_cursor(self):
        client = FakeDiscordClient(
            polls=[
                [{"id": "10", "content": "old", "author": {"id": "user-1"}}],
                [{"id": "11", "content": " latest ", "author": {"id": "user-2"}}],
            ]
        )
        listener = DiscordCommandListener(
            client=client,
            channel_id="main-channel",
            coordinator=object(),
            timezone_name="Asia/Tokyo",
            latest_handler=lambda content, **_: "保存済みの最新話一覧です" if str(content).strip() == "latest" else None,
            fetch_handler=lambda content, **_: None,
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )

        first = listener.poll_once()
        second = listener.poll_once()

        self.assertEqual([], first)
        self.assertEqual(["保存済みの最新話一覧です"], second)
        self.assertEqual(
            [{"channel_id": "main-channel", "content": "保存済みの最新話一覧です"}],
            client.sent_messages,
        )
        self.assertEqual("10", client.list_calls[1]["after"])

    def test_listener_handles_first_latest_query_after_empty_start(self):
        client = FakeDiscordClient(
            polls=[
                [],
                [{"id": "11", "content": " latest ", "author": {"id": "user-2"}}],
            ]
        )
        listener = DiscordCommandListener(
            client=client,
            channel_id="main-channel",
            coordinator=object(),
            timezone_name="Asia/Tokyo",
            latest_handler=lambda content, **_: "保存済みの最新話一覧です" if str(content).strip() == "latest" else None,
            fetch_handler=lambda content, **_: None,
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )

        first = listener.poll_once()
        second = listener.poll_once()

        self.assertEqual([], first)
        self.assertEqual(["保存済みの最新話一覧です"], second)
        self.assertEqual(
            [{"channel_id": "main-channel", "content": "保存済みの最新話一覧です"}],
            client.sent_messages,
        )
        self.assertIsNone(client.list_calls[1]["after"])

    def test_listener_handles_fetch_trigger(self):
        client = FakeDiscordClient(
            polls=[
                [{"id": "20", "content": "old", "author": {"id": "user-1"}}],
                [{"id": "21", "content": "fetch", "author": {"id": "user-2"}}],
            ]
        )
        listener = DiscordCommandListener(
            client=client,
            channel_id="main-channel",
            coordinator=object(),
            timezone_name="Asia/Tokyo",
            latest_handler=lambda content, **_: None,
            fetch_handler=lambda content, **_: (
                {"message": FETCH_ACCEPTED_MESSAGE} if str(content).strip() == "fetch" else None
            ),
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )

        listener.poll_once()
        responses = listener.poll_once()

        self.assertEqual([FETCH_ACCEPTED_MESSAGE], responses)
        self.assertEqual(FETCH_ACCEPTED_MESSAGE, client.sent_messages[0]["content"])

    def test_listener_handles_title_query(self):
        client = FakeDiscordClient(
            polls=[
                [{"id": "22", "content": "old", "author": {"id": "user-1"}}],
                [{"id": "23", "content": "title ダンジョン飯", "author": {"id": "user-2"}}],
            ]
        )
        listener = DiscordCommandListener(
            client=client,
            channel_id="main-channel",
            coordinator=object(),
            timezone_name="Asia/Tokyo",
            latest_handler=lambda content, **_: None,
            fetch_handler=lambda content, **_: None,
            title_handler=lambda content, **_: (
                "`ダンジョン飯` の title 検索を開始しました。対象媒体数: 2"
                if str(content).strip() == "title ダンジョン飯"
                else None
            ),
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )

        listener.poll_once()
        responses = listener.poll_once()

        self.assertEqual(["`ダンジョン飯` の title 検索を開始しました。対象媒体数: 2"], responses)
        self.assertEqual(
            "`ダンジョン飯` の title 検索を開始しました。対象媒体数: 2",
            client.sent_messages[0]["content"],
        )

    def test_listener_ignores_bot_messages(self):
        client = FakeDiscordClient(
            polls=[
                [{"id": "30", "content": "old", "author": {"id": "user-1"}}],
                [{"id": "31", "content": "latest", "author": {"id": "bot-user", "bot": True}}],
            ]
        )
        listener = DiscordCommandListener(
            client=client,
            channel_id="main-channel",
            coordinator=object(),
            timezone_name="Asia/Tokyo",
            latest_handler=lambda content, **_: "unexpected",
            fetch_handler=lambda content, **_: {"message": "unexpected"},
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )

        listener.poll_once()
        responses = listener.poll_once()

        self.assertEqual([], responses)
        self.assertEqual([], client.sent_messages)

    def test_split_discord_message_preserves_line_boundaries_when_possible(self):
        content = "header\n" + ("a" * 1990) + "\nfooter"

        chunks = split_discord_message(content, limit=2000)

        self.assertEqual(2, len(chunks))
        self.assertEqual("header", chunks[0].splitlines()[0])
        self.assertEqual("footer", chunks[1])


if __name__ == "__main__":
    unittest.main()
