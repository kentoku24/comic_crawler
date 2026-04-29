import os
import unittest
from unittest import mock

from nacl_test_support import SigningKey

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

if __name__ == "__main__":
    unittest.main()
