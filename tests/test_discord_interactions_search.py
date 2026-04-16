import json
import unittest

from nacl_test_support import SigningKey  # noqa: F401  # ensures nacl/google fallback is installed when needed

from manga_watch.discord_interactions import DiscordInteractionService
from manga_watch.discord_search import SEARCH_COMMAND


class RecordingSearchHandler:
    def __init__(self):
        self.start_calls = []
        self.component_calls = []

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        return {
            "content": "検索結果を選んでください。",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": "search_select:visible",
                            "options": [{"label": "作品A", "value": "https://example.com/a"}],
                        }
                    ],
                }
            ],
        }

    def handle_component(self, data, **kwargs):
        self.component_calls.append({"data": data, **kwargs})
        return {"content": "追加しました: 作品A", "components": []}


class RecordingFetchDispatcher:
    def dispatch(self):
        return {"message": "fetch ok"}


class RecordingInteractionCallbackClient:
    def __init__(self):
        self.deferred_channel_messages = []
        self.edits = []

    def defer_channel_message(self, *, interaction_id: str, interaction_token: str, ephemeral: bool = False):
        self.deferred_channel_messages.append(
            {
                "interaction_id": interaction_id,
                "interaction_token": interaction_token,
                "ephemeral": ephemeral,
            }
        )

    def edit_original_response(self, *, application_id: str, interaction_token: str, data):
        self.edits.append(
            {
                "application_id": application_id,
                "interaction_token": interaction_token,
                "data": data,
            }
        )


class DiscordInteractionSearchTests(unittest.TestCase):
    def signed_command_payload(self, command_name, *, query="まんが", source=None):
        options = [{"name": "query", "type": 3, "value": query}]
        if source is not None:
            options.append({"name": "source", "type": 3, "value": source})
        return {
            "id": "interaction-1",
            "application_id": "app-1",
            "token": "token-1",
            "type": 2,
            "data": {
                "name": command_name,
                "options": options,
            },
        }

    def test_search_command_routes_to_search_handler(self):
        search_handler = RecordingSearchHandler()
        callback_client = RecordingInteractionCallbackClient()
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=RecordingFetchDispatcher(),
            verification_disabled=True,
            search_handler=search_handler,
            interaction_callback_client=callback_client,
        )

        response = service.handle_request(
            method="POST",
            path="/",
            headers={},
            body=json.dumps(
                self.signed_command_payload(SEARCH_COMMAND, source="champion-cross")
            ).encode("utf-8"),
        )

        self.assertEqual(202, response.status_code)
        self.assertEqual(b"", response.body)
        self.assertEqual(
            [{"interaction_id": "interaction-1", "interaction_token": "token-1", "ephemeral": True}],
            callback_client.deferred_channel_messages,
        )
        self.assertEqual("検索結果を選んでください。", callback_client.edits[0]["data"]["content"])
        self.assertEqual("champion-cross", search_handler.start_calls[0]["source"])
        self.assertEqual("まんが", search_handler.start_calls[0]["query"])

    def test_search_command_routes_to_search_handler_without_source(self):
        search_handler = RecordingSearchHandler()
        callback_client = RecordingInteractionCallbackClient()
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=RecordingFetchDispatcher(),
            verification_disabled=True,
            search_handler=search_handler,
            interaction_callback_client=callback_client,
        )

        response = service.handle_request(
            method="POST",
            path="/",
            headers={},
            body=json.dumps(self.signed_command_payload(SEARCH_COMMAND)).encode("utf-8"),
        )

        self.assertEqual(202, response.status_code)
        self.assertEqual("検索結果を選んでください。", callback_client.edits[0]["data"]["content"])
        self.assertIsNone(search_handler.start_calls[0]["source"])
        self.assertEqual("まんが", search_handler.start_calls[0]["query"])

    def test_search_component_routes_to_search_handler(self):
        search_handler = RecordingSearchHandler()
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=RecordingFetchDispatcher(),
            verification_disabled=True,
            search_handler=search_handler,
        )

        response = service.handle_request(
            method="POST",
            path="/",
            headers={},
            body=json.dumps(
                {"type": 3, "data": {"custom_id": "search_select:visible", "values": ["https://example.com/a"]}}
            ).encode("utf-8"),
        )

        payload = json.loads(response.body)
        self.assertEqual(7, payload["type"])
        self.assertEqual("追加しました: 作品A", payload["data"]["content"])
        self.assertEqual("search_select:visible", search_handler.component_calls[0]["data"]["custom_id"])


if __name__ == "__main__":
    unittest.main()
