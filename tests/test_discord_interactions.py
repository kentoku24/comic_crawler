import json
import os
import unittest
from unittest import mock

from nacl_test_support import SigningKey

from manga_watch.discord_interactions import (
    CloudRunJobFetchDispatcher,
    DEFAULT_FETCH_BACKEND,
    DiscordInteractionService,
    DiscordRequestVerifier,
    InProcessFetchDispatcher,
    build_interaction_service_from_env,
    build_manual_run_request_body,
)
from manga_watch.discord_add import AddCommandHandler
from manga_watch.discord_remove import REMOVE_COMMAND
from manga_watch.runner import FETCH_ACCEPTED_MESSAGE, RunCoordinator, RunnerConfig


class RecordingFetchDispatcher:
    def __init__(self, message=FETCH_ACCEPTED_MESSAGE):
        self.message = message
        self.calls = 0

    def dispatch(self):
        self.calls += 1
        return {"message": self.message}


class FailingFetchDispatcher:
    def dispatch(self):
        raise RuntimeError("boom")


class RecordingInteractionCallbackClient:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.deferred_channel_messages = []
        self.deferred_components = []
        self.edits = []

    def defer_channel_message(self, *, interaction_id, interaction_token, ephemeral=False):
        self.events.append("callback.defer_channel_message")
        self.deferred_channel_messages.append(
            {
                "interaction_id": interaction_id,
                "interaction_token": interaction_token,
                "ephemeral": ephemeral,
            }
        )

    def defer_component(self, *, interaction_id, interaction_token):
        self.events.append("callback.defer_component")
        self.deferred_components.append(
            {
                "interaction_id": interaction_id,
                "interaction_token": interaction_token,
            }
        )

    def edit_original_response(self, *, application_id, interaction_token, data):
        self.events.append("callback.edit_original_response")
        self.edits.append(
            {
                "application_id": application_id,
                "interaction_token": interaction_token,
                "data": data,
            }
        )


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if 200 <= self.status_code < 300:
            return None
        raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


class FakeAuthorizedSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return self.response


class FakeInteractionCallbackSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.posts = []
        self.patches = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return self.response

    def patch(self, url, **kwargs):
        self.patches.append({"url": url, **kwargs})
        return self.response


class DiscordInteractionServiceTests(unittest.TestCase):
    def signed_request(self, payload, signing_key):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        timestamp = "1700000000"
        signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()
        headers = {
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": timestamp,
        }
        return headers, body

    def make_service(
        self,
        *,
        fetch_dispatcher=None,
        latest_handler=None,
        add_handler=None,
        remove_handler=None,
        interaction_callback_client=None,
        signing_key=None,
    ):
        signing_key = signing_key or SigningKey.generate()
        public_key = signing_key.verify_key.encode().hex()
        resolved_add_handler = add_handler or AddCommandHandler(
            add_subscription=lambda *_args, **_kwargs: {"action": "added", "entry": {"id": "unused"}}
        )
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=fetch_dispatcher or RecordingFetchDispatcher(),
            verifier=DiscordRequestVerifier(public_key),
            latest_handler=latest_handler or (lambda *_args, **_kwargs: "保存済みの最新話一覧です"),
            add_handler=resolved_add_handler,
            remove_handler=remove_handler,
            interaction_callback_client=interaction_callback_client,
        )
        return service, signing_key

    def signed_command_request(self, command_name, signing_key, *, options=None):
        payload = {"type": 2, "data": {"name": command_name}}
        if options is not None:
            payload["data"]["options"] = options
        return self.signed_request(payload, signing_key)

    def test_ping_request_returns_pong_when_signature_is_valid(self):
        service, signing_key = self.make_service()
        headers, body = self.signed_request({"type": 1}, signing_key)

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(200, response.status_code)
        self.assertEqual({"type": 1}, json.loads(response.body))

    def test_latest_command_returns_200_when_signature_is_valid(self):
        service, signing_key = self.make_service()
        headers, body = self.signed_request({"type": 2, "data": {"name": "latest"}}, signing_key)

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.body)
        self.assertEqual(4, payload["type"])
        self.assertIn("保存済みの最新話一覧です", payload["data"]["content"])

    def test_latest_command_defers_before_loading_and_edits_original_response(self):
        events = []

        def latest_handler(*_args, **_kwargs):
            events.append("latest_handler")
            return "保存済みの最新話一覧です"

        callback_client = RecordingInteractionCallbackClient(events)
        service, signing_key = self.make_service(
            latest_handler=latest_handler,
            interaction_callback_client=callback_client,
        )
        headers, body = self.signed_request(
            {
                "id": "interaction-1",
                "application_id": "app-1",
                "token": "token-1",
                "type": 2,
                "data": {"name": "latest"},
            },
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(202, response.status_code)
        self.assertEqual(b"", response.body)
        self.assertEqual(
            ["callback.defer_channel_message", "latest_handler", "callback.edit_original_response"],
            events,
        )
        self.assertEqual(
            [{"interaction_id": "interaction-1", "interaction_token": "token-1", "ephemeral": False}],
            callback_client.deferred_channel_messages,
        )
        self.assertEqual("app-1", callback_client.edits[0]["application_id"])
        self.assertEqual("token-1", callback_client.edits[0]["interaction_token"])
        self.assertIn("保存済みの最新話一覧です", callback_client.edits[0]["data"]["content"])

    def test_fetch_command_routes_to_dispatcher(self):
        dispatcher = RecordingFetchDispatcher()
        service, signing_key = self.make_service(fetch_dispatcher=dispatcher)
        headers, body = self.signed_request({"type": 2, "data": {"name": "fetch"}}, signing_key)

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, dispatcher.calls)
        self.assertEqual(
            FETCH_ACCEPTED_MESSAGE,
            json.loads(response.body)["data"]["content"],
        )

    def test_fetch_command_defers_before_dispatch_and_edits_original_response(self):
        events = []

        class RecordingDeferredFetchDispatcher:
            def __init__(self):
                self.calls = 0

            def dispatch(self):
                events.append("fetch_dispatch")
                self.calls += 1
                return {"message": FETCH_ACCEPTED_MESSAGE}

        dispatcher = RecordingDeferredFetchDispatcher()
        callback_client = RecordingInteractionCallbackClient(events)
        service, signing_key = self.make_service(
            fetch_dispatcher=dispatcher,
            interaction_callback_client=callback_client,
        )
        headers, body = self.signed_request(
            {
                "id": "interaction-1",
                "application_id": "app-1",
                "token": "token-1",
                "type": 2,
                "data": {"name": "fetch"},
            },
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(202, response.status_code)
        self.assertEqual(b"", response.body)
        self.assertEqual(
            ["callback.defer_channel_message", "fetch_dispatch", "callback.edit_original_response"],
            events,
        )
        self.assertEqual(
            [{"interaction_id": "interaction-1", "interaction_token": "token-1", "ephemeral": False}],
            callback_client.deferred_channel_messages,
        )
        self.assertEqual(1, dispatcher.calls)
        self.assertEqual(FETCH_ACCEPTED_MESSAGE, callback_client.edits[0]["data"]["content"])

    def test_fetch_deferred_command_edits_failure_message_when_dispatch_fails(self):
        events = []
        callback_client = RecordingInteractionCallbackClient(events)
        service, signing_key = self.make_service(
            fetch_dispatcher=FailingFetchDispatcher(),
            interaction_callback_client=callback_client,
        )
        headers, body = self.signed_request(
            {
                "id": "interaction-1",
                "application_id": "app-1",
                "token": "token-1",
                "type": 2,
                "data": {"name": "fetch"},
            },
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(202, response.status_code)
        self.assertEqual(
            ["callback.defer_channel_message", "callback.edit_original_response"],
            events,
        )
        self.assertIn("fetch の起動に失敗しました", callback_client.edits[0]["data"]["content"])

    def test_add_command_routes_url_to_watchlist_handler(self):
        recorded = {}

        class FakeAddHandler:
            def start(self, *, url, watchlist_path=None):
                recorded["url"] = url
                recorded["watchlist_path"] = watchlist_path
                return {
                    "content": "追加しました: kakuyomu:123\nseed_url: https://kakuyomu.jp/works/123"
                }

        service, signing_key = self.make_service(add_handler=FakeAddHandler())
        headers, body = self.signed_command_request(
            "add",
            signing_key,
            options=[{"name": "url", "type": 3, "value": "https://kakuyomu.jp/works/123"}],
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.body)
        self.assertEqual("https://kakuyomu.jp/works/123", recorded["url"])
        self.assertIn("追加しました", payload["data"]["content"])
        self.assertIn("kakuyomu:123", payload["data"]["content"])

    def test_add_command_defers_before_watchlist_handler_and_edits_original_response(self):
        events = []

        class FakeAddHandler:
            def start(self, *, url, watchlist_path=None):
                events.append("add_handler")
                return {
                    "content": f"追加しました: kakuyomu:123\nseed_url: {url}",
                    "components": [],
                }

        callback_client = RecordingInteractionCallbackClient(events)
        service, signing_key = self.make_service(
            add_handler=FakeAddHandler(),
            interaction_callback_client=callback_client,
        )
        headers, body = self.signed_request(
            {
                "id": "interaction-1",
                "application_id": "app-1",
                "token": "token-1",
                "type": 2,
                "data": {
                    "name": "add",
                    "options": [
                        {"name": "url", "type": 3, "value": "https://kakuyomu.jp/works/123"}
                    ],
                },
            },
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(202, response.status_code)
        self.assertEqual(
            ["callback.defer_channel_message", "add_handler", "callback.edit_original_response"],
            events,
        )
        self.assertEqual(
            [{"interaction_id": "interaction-1", "interaction_token": "token-1", "ephemeral": False}],
            callback_client.deferred_channel_messages,
        )
        self.assertIn("追加しました", callback_client.edits[0]["data"]["content"])

    def test_add_deferred_command_edits_failure_message_when_handler_raises(self):
        events = []

        class FakeAddHandler:
            def start(self, *, url, watchlist_path=None):
                events.append("add_handler")
                raise RuntimeError("boom")

        callback_client = RecordingInteractionCallbackClient(events)
        service, signing_key = self.make_service(
            add_handler=FakeAddHandler(),
            interaction_callback_client=callback_client,
        )
        headers, body = self.signed_request(
            {
                "id": "interaction-1",
                "application_id": "app-1",
                "token": "token-1",
                "type": 2,
                "data": {
                    "name": "add",
                    "options": [
                        {"name": "url", "type": 3, "value": "https://kakuyomu.jp/works/123"}
                    ],
                },
            },
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(202, response.status_code)
        self.assertEqual(
            ["callback.defer_channel_message", "add_handler", "callback.edit_original_response"],
            events,
        )
        self.assertIn("作品追加に失敗しました", callback_client.edits[0]["data"]["content"])

    def test_add_command_reports_duplicate_entry(self):
        class FakeAddHandler:
            def start(self, *, url, watchlist_path=None):
                return {"content": "既に登録済みです: kakuyomu:123"}

        service, signing_key = self.make_service(add_handler=FakeAddHandler())
        headers, body = self.signed_command_request(
            "add",
            signing_key,
            options=[{"name": "url", "type": 3, "value": "https://kakuyomu.jp/works/123"}],
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.body)
        self.assertIn("既に登録済み", payload["data"]["content"])
        self.assertIn("kakuyomu:123", payload["data"]["content"])

    def test_add_command_reports_watchlist_errors_as_interaction_message(self):
        class FakeAddHandler:
            def start(self, *, url, watchlist_path=None):
                return {"content": "追加できませんでした: Unsupported source host: example.com"}

        service, signing_key = self.make_service(add_handler=FakeAddHandler())
        headers, body = self.signed_command_request(
            "add",
            signing_key,
            options=[{"name": "url", "type": 3, "value": "https://example.com/work/1"}],
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.body)
        self.assertIn("追加できませんでした", payload["data"]["content"])
        self.assertIn("Unsupported source host: example.com", payload["data"]["content"])

    def test_add_command_requires_url_option(self):
        service, signing_key = self.make_service()
        headers, body = self.signed_command_request("add", signing_key, options=[])

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.body)
        self.assertIn("url", payload["data"]["content"])

    def test_invalid_signature_returns_401(self):
        service, signing_key = self.make_service()
        headers, body = self.signed_request({"type": 2, "data": {"name": "latest"}}, signing_key)
        headers["X-Signature-Ed25519"] = "00" * 64

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(401, response.status_code)
        self.assertEqual(b"invalid request signature", response.body)

    def test_verification_can_be_disabled_for_local_bypass(self):
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=RecordingFetchDispatcher(),
            verification_disabled=True,
            latest_handler=lambda *_args, **_kwargs: "ok",
        )
        body = json.dumps({"type": 2, "data": {"name": "latest"}}).encode("utf-8")

        response = service.handle_request(method="POST", path="/", headers={}, body=body)

        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", json.loads(response.body)["data"]["content"])

    def test_fetch_dispatch_failure_returns_structured_interaction_response(self):
        service, signing_key = self.make_service(fetch_dispatcher=FailingFetchDispatcher())
        headers, body = self.signed_request({"type": 2, "data": {"name": "fetch"}}, signing_key)

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.body)
        self.assertEqual(4, payload["type"])
        self.assertIn("fetch の起動に失敗しました", payload["data"]["content"])

    def test_remove_command_returns_ephemeral_component_response(self):
        class FakeRemoveHandler:
            def start(self, **_kwargs):
                return {
                    "content": "削除する作品を選んでください。",
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 3,
                                    "custom_id": "remove_select",
                                    "options": [{"label": "作品A", "value": "token-a"}],
                                }
                            ],
                        }
                    ],
                }

        service, signing_key = self.make_service(remove_handler=FakeRemoveHandler())
        headers, body = self.signed_request({"type": 2, "data": {"name": REMOVE_COMMAND}}, signing_key)

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        payload = json.loads(response.body)
        self.assertEqual(4, payload["type"])
        self.assertEqual(64, payload["data"]["flags"])
        self.assertEqual("remove_select", payload["data"]["components"][0]["components"][0]["custom_id"])

    def test_remove_command_defers_before_loading_options_and_edits_original_response(self):
        events = []

        class FakeRemoveHandler:
            def start(self, **_kwargs):
                events.append("remove_start")
                return {
                    "content": "削除する作品を選んでください。",
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 3,
                                    "custom_id": "remove_select",
                                    "options": [{"label": "作品A", "value": "token-a"}],
                                }
                            ],
                        }
                    ],
                }

        callback_client = RecordingInteractionCallbackClient(events)
        service, signing_key = self.make_service(
            remove_handler=FakeRemoveHandler(),
            interaction_callback_client=callback_client,
        )
        headers, body = self.signed_request(
            {
                "id": "interaction-1",
                "application_id": "app-1",
                "token": "token-1",
                "type": 2,
                "data": {"name": REMOVE_COMMAND},
            },
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        self.assertEqual(202, response.status_code)
        self.assertEqual(
            ["callback.defer_channel_message", "remove_start", "callback.edit_original_response"],
            events,
        )
        self.assertEqual(
            [{"interaction_id": "interaction-1", "interaction_token": "token-1", "ephemeral": True}],
            callback_client.deferred_channel_messages,
        )
        self.assertEqual("remove_select", callback_client.edits[0]["data"]["components"][0]["components"][0]["custom_id"])

    def test_message_component_routes_to_remove_handler(self):
        class FakeRemoveHandler:
            def __init__(self):
                self.calls = []

            def handle_component(self, data, **_kwargs):
                self.calls.append(data)
                return {"content": "updated", "components": []}

        remove_handler = FakeRemoveHandler()
        service, signing_key = self.make_service(remove_handler=remove_handler)
        headers, body = self.signed_request(
            {"type": 3, "data": {"custom_id": "remove_select", "values": ["token-a"]}},
            signing_key,
        )

        response = service.handle_request(method="POST", path="/", headers=headers, body=body)

        payload = json.loads(response.body)
        self.assertEqual(7, payload["type"])
        self.assertEqual("updated", payload["data"]["content"])
        self.assertEqual("remove_select", remove_handler.calls[0]["custom_id"])

    def test_remove_component_defers_before_handler_and_edits_original_response(self):
        class FakeRemoveHandler:
            def __init__(self, events):
                self.events = events
                self.calls = []

            def handle_component(self, data, **_kwargs):
                self.events.append("remove_component")
                self.calls.append(data)
                return {"content": "updated", "components": []}

        for custom_id, values in (
            ("remove_select", ["token-a"]),
            ("remove_page:1", []),
            ("remove_confirm:token-a", []),
            ("remove_cancel:token-a", []),
        ):
            with self.subTest(custom_id=custom_id):
                events = []
                remove_handler = FakeRemoveHandler(events)
                callback_client = RecordingInteractionCallbackClient(events)
                service, signing_key = self.make_service(
                    remove_handler=remove_handler,
                    interaction_callback_client=callback_client,
                )
                data = {"custom_id": custom_id}
                if values:
                    data["values"] = values
                headers, body = self.signed_request(
                    {
                        "id": "interaction-1",
                        "application_id": "app-1",
                        "token": "token-1",
                        "type": 3,
                        "data": data,
                    },
                    signing_key,
                )

                response = service.handle_request(method="POST", path="/", headers=headers, body=body)

                self.assertEqual(202, response.status_code)
                self.assertEqual(
                    ["callback.defer_component", "remove_component", "callback.edit_original_response"],
                    events,
                )
                self.assertEqual(
                    [{"interaction_id": "interaction-1", "interaction_token": "token-1"}],
                    callback_client.deferred_components,
                )
                self.assertEqual(custom_id, remove_handler.calls[0]["custom_id"])
                self.assertEqual("updated", callback_client.edits[0]["data"]["content"])


class FetchDispatcherTests(unittest.TestCase):
    def test_in_process_fetch_dispatcher_uses_existing_coordinator_contract(self):
        class RecordingCoordinator:
            def __init__(self):
                self.calls = []

            def start_background(self, trigger_source):
                self.calls.append(trigger_source)
                return {"accepted": True, "message": FETCH_ACCEPTED_MESSAGE}

        coordinator = RecordingCoordinator()

        dispatcher = InProcessFetchDispatcher(coordinator)  # type: ignore[arg-type]
        outcome = dispatcher.dispatch()

        self.assertEqual(["discord_fetch"], coordinator.calls)
        self.assertEqual(FETCH_ACCEPTED_MESSAGE, outcome["message"])

    def test_cloud_run_job_fetch_dispatcher_posts_manual_override(self):
        session = FakeAuthorizedSession()
        dispatcher = CloudRunJobFetchDispatcher(
            project="demo-project",
            region="asia-northeast1",
            job_name="comic-crawler-job",
            session_factory=lambda: session,
        )

        outcome = dispatcher.dispatch()

        self.assertTrue(outcome["accepted"])
        self.assertEqual(
            {
                "overrides": {
                    "containerOverrides": [
                        {"env": [{"name": "MANGA_WATCH_TRIGGER_SOURCE", "value": "manual"}]}
                    ]
                }
            },
            session.posts[0]["json"],
        )
        self.assertIn("/jobs/comic-crawler-job:run", session.posts[0]["url"])

    def test_build_manual_run_request_body_uses_manual_alias(self):
        self.assertEqual(
            {
                "overrides": {
                    "containerOverrides": [
                        {"env": [{"name": "MANGA_WATCH_TRIGGER_SOURCE", "value": "manual"}]}
                    ]
                }
            },
            build_manual_run_request_body(),
        )

    def test_discord_interaction_callback_client_uses_shorter_timeout_for_defer(self):
        from manga_watch.discord_interactions import DiscordInteractionCallbackClient

        session = FakeInteractionCallbackSession()
        client = DiscordInteractionCallbackClient(
            session=session,
            timeout=15,
            defer_timeout=2,
        )

        client.defer_component(interaction_id="interaction-1", interaction_token="token-1")
        client.defer_channel_message(
            interaction_id="interaction-2",
            interaction_token="token-2",
            ephemeral=True,
        )
        client.edit_original_response(
            application_id="app-1",
            interaction_token="token-1",
            data={"content": "updated"},
        )

        self.assertEqual(2, session.posts[0]["timeout"])
        self.assertEqual(2, session.posts[1]["timeout"])
        self.assertEqual(5, session.posts[1]["json"]["type"])
        self.assertEqual(64, session.posts[1]["json"]["data"]["flags"])
        self.assertEqual(15, session.patches[0]["timeout"])


class BuildInteractionServiceFromEnvTests(unittest.TestCase):
    def test_build_interaction_service_uses_cloud_run_job_backend_without_discord_outbound(self):
        runner_config = RunnerConfig(
            timezone_name="Asia/Tokyo",
            watchlist_path="manga_watch/watchlist.json",
            crawl_schedule="0 19 * * *",
            crawl_interval=None,
            run_on_startup=True,
            notifier_config=mock.Mock(),
            discord_outbound_config=None,
        )
        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_APPLICATION_PUBLIC_KEY": SigningKey.generate().verify_key.encode().hex(),
                "MANGA_WATCH_FETCH_BACKEND": "cloud-run-job",
                "MANGA_WATCH_GCP_PROJECT": "star-light-breaker",
                "MANGA_WATCH_CLOUD_RUN_REGION": "asia-northeast1",
                "MANGA_WATCH_CLOUD_RUN_JOB_NAME": "comic-crawler-job",
            },
            clear=True,
        ):
            service = build_interaction_service_from_env(
                runner_config=runner_config,
                session_factory=lambda: FakeAuthorizedSession(),
            )

        self.assertEqual("Asia/Tokyo", service.timezone_name)
        self.assertFalse(service.verification_disabled)
        self.assertIsNotNone(service.remove_handler)
        self.assertEqual("json", service.remove_handler.backend)

    def test_build_interaction_service_defaults_fetch_backend_to_coordinator(self):
        runner_config = RunnerConfig(
            timezone_name="Asia/Tokyo",
            watchlist_path="manga_watch/watchlist.json",
            crawl_schedule="0 19 * * *",
            crawl_interval=None,
            run_on_startup=True,
            notifier_config=mock.Mock(),
            discord_outbound_config=None,
        )
        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_APPLICATION_PUBLIC_KEY": SigningKey.generate().verify_key.encode().hex(),
                "MANGA_WATCH_STORAGE_BACKEND": "firestore",
            },
            clear=True,
        ):
            with mock.patch("manga_watch.discord_interactions.build_named_notifiers", return_value={}):
                service = build_interaction_service_from_env(runner_config=runner_config)

        self.assertEqual(DEFAULT_FETCH_BACKEND, os.environ.get("MANGA_WATCH_FETCH_BACKEND", DEFAULT_FETCH_BACKEND))
        self.assertFalse(service.verification_disabled)
        self.assertIsNotNone(service.remove_handler)
        self.assertEqual("firestore", service.remove_handler.backend)
        self.assertIsNotNone(service.supertwins_search_handler)
        self.assertEqual("firestore", service.supertwins_search_handler.backend)
        self.assertIsNotNone(service.supertwins_manage_handler)
        self.assertEqual("firestore", service.supertwins_manage_handler.backend)

    def test_build_interaction_service_configures_github_issue_reporter_when_env_present(self):
        runner_config = RunnerConfig(
            timezone_name="Asia/Tokyo",
            watchlist_path="manga_watch/watchlist.json",
            crawl_schedule="0 19 * * *",
            crawl_interval=None,
            run_on_startup=True,
            notifier_config=mock.Mock(),
            discord_outbound_config=None,
        )
        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_APPLICATION_PUBLIC_KEY": SigningKey.generate().verify_key.encode().hex(),
                "MANGA_WATCH_FETCH_BACKEND": "cloud-run-job",
                "MANGA_WATCH_GCP_PROJECT": "star-light-breaker",
                "MANGA_WATCH_CLOUD_RUN_REGION": "asia-northeast1",
                "MANGA_WATCH_CLOUD_RUN_JOB_NAME": "comic-crawler-job",
                "MANGA_WATCH_GITHUB_TOKEN": "github-token",
                "MANGA_WATCH_GITHUB_REPOSITORY": "kentoku24/comic_crawler",
            },
            clear=True,
        ):
            service = build_interaction_service_from_env(
                runner_config=runner_config,
                session_factory=lambda: FakeAuthorizedSession(),
            )

        self.assertIsNotNone(service.add_handler)
        self.assertIsNotNone(service.add_handler.unsupported_source_reporter)


if __name__ == "__main__":
    unittest.main()
