import json
import sys
import types
import unittest


google = types.ModuleType("google")
google_auth = types.ModuleType("google.auth")
google_auth_transport = types.ModuleType("google.auth.transport")
google_auth_transport_requests = types.ModuleType("google.auth.transport.requests")


class _AuthorizedSession:
    def __init__(self, *args, **kwargs):
        pass


google_auth.default = lambda scopes=None: (object(), None)
google_auth_transport_requests.AuthorizedSession = _AuthorizedSession
google.auth = google_auth
sys.modules["google"] = google
sys.modules["google.auth"] = google_auth
sys.modules["google.auth.transport"] = google_auth_transport
sys.modules["google.auth.transport.requests"] = google_auth_transport_requests

nacl = types.ModuleType("nacl")
nacl_exceptions = types.ModuleType("nacl.exceptions")
nacl_signing = types.ModuleType("nacl.signing")


class _BadSignatureError(Exception):
    pass


class _VerifyKey:
    def __init__(self, *args, **kwargs):
        pass

    def verify(self, *args, **kwargs):
        return True


nacl_exceptions.BadSignatureError = _BadSignatureError
nacl_signing.VerifyKey = _VerifyKey
sys.modules["nacl"] = nacl
sys.modules["nacl.exceptions"] = nacl_exceptions
sys.modules["nacl.signing"] = nacl_signing

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


class DiscordInteractionSearchTests(unittest.TestCase):
    def signed_command_payload(self, command_name):
        return {
            "type": 2,
            "data": {
                "name": command_name,
                "options": [
                    {"name": "source", "type": 3, "value": "champion-cross"},
                    {"name": "query", "type": 3, "value": "まんが"},
                ],
            },
        }

    def test_search_command_routes_to_search_handler(self):
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
            body=json.dumps(self.signed_command_payload(SEARCH_COMMAND)).encode("utf-8"),
        )

        payload = json.loads(response.body)
        self.assertEqual(4, payload["type"])
        self.assertEqual(64, payload["data"]["flags"])
        self.assertEqual("検索結果を選んでください。", payload["data"]["content"])
        self.assertEqual("champion-cross", search_handler.start_calls[0]["source"])
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
