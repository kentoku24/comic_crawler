import json
import unittest

from nacl_test_support import SigningKey  # noqa: F401

from manga_watch.discord_interactions import DiscordInteractionService
from manga_watch.discord_where import WHERE_COMMAND


class RecordingWhereHandler:
    def __init__(self, events=None):
        self.events = events
        self.start_calls = []
        self.component_calls = []

    def start(self, **kwargs):
        if self.events is not None:
            self.events.append("where.start")
        self.start_calls.append(kwargs)
        return {
            "content": "where 候補を選んでください。",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": "where_select:token",
                            "options": [{"label": "作品A", "value": "0"}],
                        }
                    ],
                }
            ],
        }

    def handle_component(self, data, **kwargs):
        if self.events is not None:
            self.events.append("where.handle_component")
        self.component_calls.append({"data": data, **kwargs})
        return {"content": "ComicWalker: 今すぐ無料", "components": []}


class RecordingFetchDispatcher:
    def dispatch(self):
        return {"message": "fetch ok"}


class RecordingInteractionCallbackClient:
    def __init__(self, events=None):
        self.events = events
        self.deferred_channel_messages = []
        self.deferred_components = []
        self.edits = []

    def defer_channel_message(self, *, interaction_id: str, interaction_token: str, ephemeral: bool = False):
        if self.events is not None:
            self.events.append("callback.defer_channel_message")
        self.deferred_channel_messages.append(
            {
                "interaction_id": interaction_id,
                "interaction_token": interaction_token,
                "ephemeral": ephemeral,
            }
        )

    def defer_component(self, *, interaction_id: str, interaction_token: str):
        if self.events is not None:
            self.events.append("callback.defer_component")
        self.deferred_components.append(
            {
                "interaction_id": interaction_id,
                "interaction_token": interaction_token,
            }
        )

    def edit_original_response(self, *, application_id: str, interaction_token: str, data):
        if self.events is not None:
            self.events.append("callback.edit_original_response")
        self.edits.append(
            {
                "application_id": application_id,
                "interaction_token": interaction_token,
                "data": data,
            }
        )


class DiscordInteractionWhereTests(unittest.TestCase):
    def test_where_command_defers_when_callback_client_is_available(self):
        events = []
        where_handler = RecordingWhereHandler(events=events)
        callback_client = RecordingInteractionCallbackClient(events=events)
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=RecordingFetchDispatcher(),
            verification_disabled=True,
            where_handler=where_handler,
            interaction_callback_client=callback_client,
        )
        payload = {
            "id": "interaction-1",
            "application_id": "app-1",
            "token": "token-1",
            "type": 2,
            "data": {
                "name": WHERE_COMMAND,
                "options": [
                    {"name": "query", "type": 3, "value": "ニセモノの錬金術師"},
                    {"name": "episode", "type": 3, "value": "第1話"},
                ],
            },
        }

        response = service.handle_request(method="POST", path="/", headers={}, body=json.dumps(payload).encode())

        self.assertEqual(202, response.status_code)
        self.assertEqual(b"", response.body)
        self.assertEqual(
            [{"interaction_id": "interaction-1", "interaction_token": "token-1", "ephemeral": True}],
            callback_client.deferred_channel_messages,
        )
        self.assertEqual("where 候補を選んでください。", callback_client.edits[0]["data"]["content"])
        self.assertEqual(
            [{"query": "ニセモノの錬金術師", "episode": "第1話"}],
            where_handler.start_calls,
        )
        self.assertEqual(
            [
                "callback.defer_channel_message",
                "where.start",
                "callback.edit_original_response",
            ],
            events,
        )

if __name__ == "__main__":
    unittest.main()
