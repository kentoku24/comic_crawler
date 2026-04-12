import json
import unittest

from nacl_test_support import SigningKey

from manga_watch.discord_add import AddCommandHandler
from manga_watch.discord_interactions import (
    DiscordInteractionService,
    DiscordRequestVerifier,
)
from manga_watch.discord_supertwins_manage import SUPERTWINS_MANAGE_COMMAND
from manga_watch.discord_supertwins_search import SUPERTWINS_SEARCH_COMMAND


class RecordingFetchDispatcher:
    def dispatch(self):
        return {"message": "ok"}


class RecordingInteractionCallbackClient:
    def __init__(self):
        self.defer_calls = []
        self.edit_calls = []

    def defer_component(self, *, interaction_id, interaction_token):
        self.defer_calls.append(
            {
                "interaction_id": interaction_id,
                "interaction_token": interaction_token,
            }
        )

    def edit_original_response(self, *, application_id, interaction_token, data):
        self.edit_calls.append(
            {
                "application_id": application_id,
                "interaction_token": interaction_token,
                "data": data,
            }
        )


class DiscordSupertwinsInteractionTests(unittest.TestCase):
    def make_service(
        self,
        *,
        supertwins_search_handler=None,
        supertwins_manage_handler=None,
        interaction_callback_client=None,
    ):
        signing_key = SigningKey.generate()
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=RecordingFetchDispatcher(),
            verifier=DiscordRequestVerifier(signing_key.verify_key.encode().hex()),
            latest_handler=lambda *_args, **_kwargs: "latest",
            add_handler=AddCommandHandler(
                add_subscription=lambda *_args, **_kwargs: {"action": "added", "entry": {"id": "unused"}}
            ),
            supertwins_search_handler=supertwins_search_handler,
            supertwins_manage_handler=supertwins_manage_handler,
            interaction_callback_client=interaction_callback_client,
        )
        return service, signing_key

    def signed_request(self, payload, signing_key):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        timestamp = "1700000000"
        signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()
        headers = {
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": timestamp,
        }
        return headers, body

    def test_supertwins_search_command_routes_to_ephemeral_handler(self):
        class FakeSearchHandler:
            def __init__(self):
                self.calls = []

            def start(self, **kwargs):
                self.calls.append(kwargs)
                return {"content": "候補検索はまだ有効化されていません。", "components": []}

        handler = FakeSearchHandler()
        service, signing_key = self.make_service(supertwins_search_handler=handler)
        headers, body = self.signed_request(
            {"type": 2, "data": {"name": SUPERTWINS_SEARCH_COMMAND}},
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        payload = json.loads(response.body)
        self.assertEqual(4, payload["type"])
        self.assertEqual(64, payload["data"]["flags"])
        self.assertEqual("候補検索はまだ有効化されていません。", payload["data"]["content"])
        self.assertEqual(1, len(handler.calls))

    def test_supertwins_manage_command_routes_to_ephemeral_handler(self):
        class FakeManageHandler:
            def __init__(self):
                self.calls = []

            def start(self, **kwargs):
                self.calls.append(kwargs)
                return {"content": "supertwins 管理はまだ有効化されていません。", "components": []}

        handler = FakeManageHandler()
        service, signing_key = self.make_service(supertwins_manage_handler=handler)
        headers, body = self.signed_request(
            {"type": 2, "data": {"name": SUPERTWINS_MANAGE_COMMAND}},
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        payload = json.loads(response.body)
        self.assertEqual(4, payload["type"])
        self.assertEqual(64, payload["data"]["flags"])
        self.assertEqual("supertwins 管理はまだ有効化されていません。", payload["data"]["content"])
        self.assertEqual(1, len(handler.calls))

    def test_supertwins_search_component_prefix_routes_to_handler(self):
        class FakeSearchHandler:
            def __init__(self):
                self.calls = []

            def handle_component(self, data, **kwargs):
                self.calls.append({"data": data, **kwargs})
                return {"content": "updated-search", "components": []}

        handler = FakeSearchHandler()
        service, signing_key = self.make_service(supertwins_search_handler=handler)
        headers, body = self.signed_request(
            {"type": 3, "data": {"custom_id": "supertwins_search:placeholder"}},
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        payload = json.loads(response.body)
        self.assertEqual(7, payload["type"])
        self.assertEqual("updated-search", payload["data"]["content"])
        self.assertEqual("supertwins_search:placeholder", handler.calls[0]["data"]["custom_id"])

    def test_supertwins_search_root_select_defers_and_edits_original_message(self):
        class FakeSearchHandler:
            def __init__(self):
                self.calls = []

            def handle_component(self, data, **kwargs):
                self.calls.append({"data": data, **kwargs})
                return {
                    "content": "他媒体候補を選んでください。",
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 3,
                                    "custom_id": "supertwins_search:results:token-1",
                                    "options": [{"label": "作品A", "value": "candidate-1"}],
                                }
                            ],
                        }
                    ],
                }

        callback_client = RecordingInteractionCallbackClient()
        handler = FakeSearchHandler()
        service, signing_key = self.make_service(
            supertwins_search_handler=handler,
            interaction_callback_client=callback_client,
        )
        headers, body = self.signed_request(
            {
                "id": "interaction-1",
                "application_id": "app-1",
                "token": "token-1",
                "type": 3,
                "data": {
                    "custom_id": "supertwins_search_work_select",
                    "values": ["root-1"],
                },
            },
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(202, response.status_code)
        self.assertEqual(b"", response.body)
        self.assertEqual(
            [{"interaction_id": "interaction-1", "interaction_token": "token-1"}],
            callback_client.defer_calls,
        )
        self.assertEqual("app-1", callback_client.edit_calls[0]["application_id"])
        self.assertEqual("token-1", callback_client.edit_calls[0]["interaction_token"])
        self.assertEqual(
            "他媒体候補を選んでください。",
            callback_client.edit_calls[0]["data"]["content"],
        )
        self.assertEqual("supertwins_search_work_select", handler.calls[0]["data"]["custom_id"])

    def test_supertwins_search_result_select_still_uses_inline_update_message(self):
        class FakeSearchHandler:
            def __init__(self):
                self.calls = []

            def handle_component(self, data, **kwargs):
                self.calls.append({"data": data, **kwargs})
                return {"content": "updated-search", "components": []}

        callback_client = RecordingInteractionCallbackClient()
        handler = FakeSearchHandler()
        service, signing_key = self.make_service(
            supertwins_search_handler=handler,
            interaction_callback_client=callback_client,
        )
        headers, body = self.signed_request(
            {
                "id": "interaction-1",
                "application_id": "app-1",
                "token": "token-1",
                "type": 3,
                "data": {
                    "custom_id": "supertwins_search:results:token-1",
                    "values": ["candidate-1"],
                },
            },
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        payload = json.loads(response.body)
        self.assertEqual(7, payload["type"])
        self.assertEqual("updated-search", payload["data"]["content"])
        self.assertEqual([], callback_client.defer_calls)
        self.assertEqual([], callback_client.edit_calls)

    def test_supertwins_manage_component_prefix_routes_to_handler(self):
        class FakeManageHandler:
            def __init__(self):
                self.calls = []

            def handle_component(self, data, **kwargs):
                self.calls.append({"data": data, **kwargs})
                return {"content": "updated-manage", "components": []}

        handler = FakeManageHandler()
        service, signing_key = self.make_service(supertwins_manage_handler=handler)
        headers, body = self.signed_request(
            {"type": 3, "data": {"custom_id": "supertwins_manage:placeholder"}},
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        payload = json.loads(response.body)
        self.assertEqual(7, payload["type"])
        self.assertEqual("updated-manage", payload["data"]["content"])
        self.assertEqual("supertwins_manage:placeholder", handler.calls[0]["data"]["custom_id"])


if __name__ == "__main__":
    unittest.main()
