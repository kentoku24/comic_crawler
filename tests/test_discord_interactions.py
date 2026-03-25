import json
import os
import unittest
from unittest import mock

from nacl.signing import SigningKey

from manga_watch.discord_interactions import (
    CloudRunJobFetchDispatcher,
    DEFAULT_FETCH_BACKEND,
    DiscordInteractionService,
    DiscordRequestVerifier,
    InProcessFetchDispatcher,
    build_interaction_service_from_env,
    build_manual_run_request_body,
)
from manga_watch.runner import FETCH_ACCEPTED_MESSAGE, RunCoordinator, RunnerConfig


class RecordingFetchDispatcher:
    def __init__(self, message=FETCH_ACCEPTED_MESSAGE):
        self.message = message
        self.calls = 0

    def dispatch(self):
        self.calls += 1
        return {"message": self.message}


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class FakeAuthorizedSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
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

    def make_service(self, *, fetch_dispatcher=None, latest_handler=None, signing_key=None):
        signing_key = signing_key or SigningKey.generate()
        public_key = signing_key.verify_key.encode().hex()
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=fetch_dispatcher or RecordingFetchDispatcher(),
            verifier=DiscordRequestVerifier(public_key),
            latest_handler=latest_handler or (lambda *_args, **_kwargs: "保存済みの最新話一覧です"),
        )
        return service, signing_key

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
            },
            clear=True,
        ):
            with mock.patch("manga_watch.discord_interactions.build_named_notifiers", return_value={}):
                service = build_interaction_service_from_env(runner_config=runner_config)

        self.assertEqual(DEFAULT_FETCH_BACKEND, os.environ.get("MANGA_WATCH_FETCH_BACKEND", DEFAULT_FETCH_BACKEND))
        self.assertFalse(service.verification_disabled)


if __name__ == "__main__":
    unittest.main()
