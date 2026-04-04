import os
import unittest
from unittest import mock

from nacl.signing import SigningKey

from manga_watch import run_service


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
