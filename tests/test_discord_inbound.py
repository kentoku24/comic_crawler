import unittest
import threading

from manga_watch.discord_inbound import DiscordCommandListener, split_discord_message


class ImmediateThread:
    def __init__(self, *, target, daemon=None, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name

    def start(self):
        self.target()


class FakeDiscordClient:
    def __init__(self, *, current_user_id="bot-user", polls=None, reaction_error=None):
        self.current_user_id = current_user_id
        self.polls = list(polls or [])
        self.reaction_error = reaction_error
        self.list_calls = []
        self.sent_messages = []
        self.reactions = []
        self.operations = []

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
        self.operations.append(("send_message", channel_id, content))
        self.sent_messages.append(
            {
                "channel_id": channel_id,
                "content": content,
            }
        )

    def add_reaction(self, channel_id, message_id, emoji):
        self.operations.append(("add_reaction", channel_id, message_id, emoji))
        if self.reaction_error is not None:
            raise self.reaction_error
        self.reactions.append(
            {
                "channel_id": channel_id,
                "message_id": message_id,
                "emoji": emoji,
            }
        )


class BlockingReactionClient(FakeDiscordClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.reaction_started = threading.Event()
        self.allow_reaction_finish = threading.Event()

    def add_reaction(self, channel_id, message_id, emoji):
        self.operations.append(("add_reaction", channel_id, message_id, emoji))
        self.reaction_started.set()
        self.allow_reaction_finish.wait(1.0)
        self.reactions.append(
            {
                "channel_id": channel_id,
                "message_id": message_id,
                "emoji": emoji,
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
            thread_factory=ImmediateThread,
        )

        first = listener.poll_once()
        second = listener.poll_once()

        self.assertEqual([], first)
        self.assertEqual(["保存済みの最新話一覧です"], second)
        self.assertEqual(
            [{"channel_id": "main-channel", "content": "保存済みの最新話一覧です"}],
            client.sent_messages,
        )
        self.assertEqual(
            [{"channel_id": "main-channel", "message_id": "11", "emoji": "✅"}],
            client.reactions,
        )
        self.assertEqual(("add_reaction", "main-channel", "11", "✅"), client.operations[0])
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
            thread_factory=ImmediateThread,
        )

        first = listener.poll_once()
        second = listener.poll_once()

        self.assertEqual([], first)
        self.assertEqual(["保存済みの最新話一覧です"], second)
        self.assertEqual(
            [{"channel_id": "main-channel", "content": "保存済みの最新話一覧です"}],
            client.sent_messages,
        )
        self.assertEqual(
            [{"channel_id": "main-channel", "message_id": "11", "emoji": "✅"}],
            client.reactions,
        )
        self.assertIsNone(client.list_calls[1]["after"])

    def test_listener_handles_fetch_trigger(self):
        handler_calls = []
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
            fetch_handler=lambda content, **_: handler_calls.append(str(content).strip()) or {"message": "ignored"},
            report_logger=lambda _: None,
            error_logger=lambda _: None,
            thread_factory=ImmediateThread,
        )

        listener.poll_once()
        responses = listener.poll_once()

        self.assertEqual([], responses)
        self.assertEqual(["fetch"], handler_calls)
        self.assertEqual([], client.sent_messages)
        self.assertEqual(
            [{"channel_id": "main-channel", "message_id": "21", "emoji": "✅"}],
            client.reactions,
        )
        self.assertEqual(("add_reaction", "main-channel", "21", "✅"), client.operations[0])

    def test_listener_logs_reaction_failure_but_still_replies_to_latest(self):
        logged_errors = []
        client = FakeDiscordClient(
            polls=[
                [{"id": "40", "content": "old", "author": {"id": "user-1"}}],
                [{"id": "41", "content": "latest", "author": {"id": "user-2"}}],
            ],
            reaction_error=RuntimeError("reaction failed"),
        )
        listener = DiscordCommandListener(
            client=client,
            channel_id="main-channel",
            coordinator=object(),
            timezone_name="Asia/Tokyo",
            latest_handler=lambda content, **_: "保存済みの最新話一覧です" if str(content).strip() == "latest" else None,
            fetch_handler=lambda content, **_: None,
            report_logger=lambda _: None,
            error_logger=logged_errors.append,
            thread_factory=ImmediateThread,
        )

        listener.poll_once()
        responses = listener.poll_once()

        self.assertEqual(["保存済みの最新話一覧です"], responses)
        self.assertEqual(
            [{"channel_id": "main-channel", "content": "保存済みの最新話一覧です"}],
            client.sent_messages,
        )
        self.assertEqual(1, len(logged_errors))
        self.assertIn("ack reaction failed", logged_errors[0])

    def test_listener_logs_reaction_failure_but_still_starts_fetch(self):
        logged_errors = []
        handler_calls = []
        client = FakeDiscordClient(
            polls=[
                [{"id": "50", "content": "old", "author": {"id": "user-1"}}],
                [{"id": "51", "content": "fetch", "author": {"id": "user-2"}}],
            ],
            reaction_error=RuntimeError("reaction failed"),
        )
        listener = DiscordCommandListener(
            client=client,
            channel_id="main-channel",
            coordinator=object(),
            timezone_name="Asia/Tokyo",
            latest_handler=lambda content, **_: None,
            fetch_handler=lambda content, **_: handler_calls.append(str(content).strip()) or {"message": "ignored"},
            report_logger=lambda _: None,
            error_logger=logged_errors.append,
            thread_factory=ImmediateThread,
        )

        listener.poll_once()
        responses = listener.poll_once()

        self.assertEqual([], responses)
        self.assertEqual(["fetch"], handler_calls)
        self.assertEqual([], client.sent_messages)
        self.assertEqual(1, len(logged_errors))
        self.assertIn("ack reaction failed", logged_errors[0])

    def test_listener_starts_fetch_after_reaction_attempt_begins_without_waiting_for_delivery(self):
        handler_calls = []
        client = BlockingReactionClient(
            polls=[
                [{"id": "60", "content": "old", "author": {"id": "user-1"}}],
                [{"id": "61", "content": "fetch", "author": {"id": "user-2"}}],
            ]
        )
        listener = DiscordCommandListener(
            client=client,
            channel_id="main-channel",
            coordinator=object(),
            timezone_name="Asia/Tokyo",
            latest_handler=lambda content, **_: None,
            fetch_handler=lambda content, **_: (
                self.assertTrue(client.reaction_started.is_set()),
                handler_calls.append(str(content).strip()),
                {"message": "ignored"},
            )[-1],
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )

        listener.poll_once()
        responses = listener.poll_once()

        self.assertEqual([], responses)
        self.assertEqual(["fetch"], handler_calls)
        self.assertEqual([], client.sent_messages)
        self.assertEqual([], client.reactions)

        client.allow_reaction_finish.set()
        self.assertTrue(client.reaction_started.wait(0.5))

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
            thread_factory=ImmediateThread,
        )

        listener.poll_once()
        responses = listener.poll_once()

        self.assertEqual([], responses)
        self.assertEqual([], client.sent_messages)
        self.assertEqual([], client.reactions)

    def test_split_discord_message_preserves_line_boundaries_when_possible(self):
        content = "header\n" + ("a" * 1990) + "\nfooter"

        chunks = split_discord_message(content, limit=2000)

        self.assertEqual(2, len(chunks))
        self.assertEqual("header", chunks[0].splitlines()[0])
        self.assertEqual("footer", chunks[1])


if __name__ == "__main__":
    unittest.main()
