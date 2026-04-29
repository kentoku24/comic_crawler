import http.client
import json
import os
import threading
import unittest
from unittest import mock

from nacl_test_support import SigningKey

from manga_watch.discord_interactions import DiscordInteractionService, DiscordRequestVerifier
from manga_watch import run_service


class FakeInteractionService:
    def __init__(self, response=None):
        self.response = response or mock.Mock(
            status_code=200,
            body=b"delegated",
            content_type="text/plain; charset=utf-8",
        )
        self.interaction_path = "/"
        self.calls = []

    def handle_request(self, *, method, path, headers, body):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers),
                "body": body,
            }
        )
        return self.response


class FakeServer:
    instances = []

    def __init__(self, address, handler):
        self.address = address
        self.handler = handler
        self.closed = False
        FakeServer.instances.append(self)

    def serve_forever(self):
        return None

    def server_close(self):
        self.closed = True


class RunServiceTests(unittest.TestCase):
    def setUp(self):
        FakeServer.instances = []

    def test_build_http_response_returns_ok_for_healthz_get(self):
        service = FakeInteractionService()

        response = run_service.build_http_response(
            service,
            method="GET",
            path="/healthz",
            headers={},
            body=b"",
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"ok", response.body)
        self.assertEqual("text/plain; charset=utf-8", response.content_type)
        self.assertEqual([], service.calls)

    def test_build_http_response_delegates_non_health_requests_to_interaction_service(self):
        service = FakeInteractionService()

        response = run_service.build_http_response(
            service,
            method="POST",
            path="/",
            headers={"X-Test": "1"},
            body=b'{"type":1}',
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"delegated", response.body)
        self.assertEqual(
            [
                {
                    "method": "POST",
                    "path": "/",
                    "headers": {"X-Test": "1"},
                    "body": b'{"type":1}',
                }
            ],
            service.calls,
        )

    def test_build_http_response_delegates_when_health_path_matches_interaction_path(self):
        service = FakeInteractionService()
        service.interaction_path = "/healthz"

        response = run_service.build_http_response(
            service,
            method="GET",
            path="/healthz",
            headers={"X-Test": "1"},
            body=b"",
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"delegated", response.body)
        self.assertEqual(
            [
                {
                    "method": "GET",
                    "path": "/healthz",
                    "headers": {"X-Test": "1"},
                    "body": b"",
                }
            ],
            service.calls,
        )

    def test_main_boots_with_cloud_run_job_backend_minimal_env(self):
        public_key = SigningKey.generate().verify_key.encode().hex()
        with mock.patch.dict(
            os.environ,
            {
                "PORT": "8123",
                "TZ": "Asia/Tokyo",
                "DISCORD_BOT_TOKEN": "discord-token",
                "DISCORD_APPLICATION_ID": "application-id",
                "DISCORD_APPLICATION_PUBLIC_KEY": public_key,
                "MANGA_WATCH_FETCH_BACKEND": "cloud-run-job",
                "MANGA_WATCH_GCP_PROJECT": "demo-project",
                "MANGA_WATCH_CLOUD_RUN_REGION": "asia-northeast1",
                "MANGA_WATCH_CLOUD_RUN_JOB_NAME": "comic-crawler-job",
                "MANGA_WATCH_STORAGE_BACKEND": "firestore",
                "MANGA_WATCH_FIRESTORE_PROJECT": "demo-project",
            },
            clear=True,
        ):
            with mock.patch("manga_watch.run_service.ThreadingHTTPServer", FakeServer):
                with mock.patch("manga_watch.run_service.ensure_commands_registered_from_env") as register_mock:
                    exit_code = run_service.main()

        self.assertEqual(0, exit_code)
        self.assertEqual(("0.0.0.0", 8123), FakeServer.instances[0].address)
        self.assertTrue(FakeServer.instances[0].closed)
        register_mock.assert_called_once_with()

    def test_main_returns_configuration_error_when_startup_registration_fails(self):
        public_key = SigningKey.generate().verify_key.encode().hex()
        with mock.patch.dict(
            os.environ,
            {
                "PORT": "8123",
                "TZ": "Asia/Tokyo",
                "DISCORD_BOT_TOKEN": "discord-token",
                "DISCORD_APPLICATION_ID": "application-id",
                "DISCORD_APPLICATION_PUBLIC_KEY": public_key,
                "MANGA_WATCH_FETCH_BACKEND": "cloud-run-job",
                "MANGA_WATCH_GCP_PROJECT": "demo-project",
                "MANGA_WATCH_CLOUD_RUN_REGION": "asia-northeast1",
                "MANGA_WATCH_CLOUD_RUN_JOB_NAME": "comic-crawler-job",
            },
            clear=True,
        ):
            with mock.patch(
                "manga_watch.run_service.ensure_commands_registered_from_env",
                side_effect=RuntimeError("registration failed"),
            ):
                exit_code = run_service.main()

        self.assertEqual(2, exit_code)

    def test_http_server_accepts_signed_discord_post(self):
        """Pseudo-E2E for HTTP entrypoint using only local in-process components.

        Notes for CI (GitHub Actions):
        - This test does NOT call Discord API or Cloud Run/GCP endpoints.
        - It starts ThreadingHTTPServer on 127.0.0.1 with an ephemeral port.
        - The request is sent via http.client to that local server only.
        - fetch_dispatcher is a no-op stub, so no external backend launch occurs.
        - DB access is not required:
          - `latest_handler` is an inline lambda that returns a fixed string.
          - command registration / watchlist / storage initialization is not executed.
        - Fixture test data is not required because request/response payloads are
          built inline in this test.
        """

        class NoopFetchDispatcher:
            def dispatch(self):
                return {"message": "ok"}

        signing_key = SigningKey.generate()
        public_key = signing_key.verify_key.encode().hex()
        service = DiscordInteractionService(
            timezone_name="Asia/Tokyo",
            fetch_dispatcher=NoopFetchDispatcher(),
            verifier=DiscordRequestVerifier(public_key),
            latest_handler=lambda *_args, **_kwargs: "最新話です",
        )
        server = run_service.ThreadingHTTPServer(("127.0.0.1", 0), run_service.build_request_handler(service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = {"type": 2, "data": {"name": "latest"}}
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            timestamp = "1700000000"
            signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()

            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            conn.request(
                "POST",
                "/",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature-Ed25519": signature,
                    "X-Signature-Timestamp": timestamp,
                },
            )
            response = conn.getresponse()
            response_body = response.read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(200, response.status)
        parsed = json.loads(response_body)
        self.assertEqual(4, parsed["type"])
        self.assertIn("最新話です", parsed["data"]["content"])


if __name__ == "__main__":
    unittest.main()
