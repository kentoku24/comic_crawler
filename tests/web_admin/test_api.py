from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from manga_watch.storage import save_state, save_watchlist


@override_settings(ROOT_URLCONF="web_admin.project.urls")
class ApiTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        watchlist_path = Path(self.tmpdir.name) / "watchlist.json"
        state_path = Path(self.tmpdir.name) / "state.json"
        save_watchlist(
            {
                "version": 2,
                "works": [
                    {
                        "id": "work-1",
                        "source": "comic-walker",
                        "seed_url": "https://comic-walker.com/detail/KC_123456_S",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    }
                ],
            },
            path=str(watchlist_path),
        )
        save_state(
            {
                "version": 2,
                "works": {},
                "last_run_at": None,
                "notification_outbox": [],
                "discord_delivery": {"daily_notification": {"delivered_latest_keys": {}, "pending_messages": []}},
            },
            path=str(state_path),
        )
        self.env = mock.patch.dict(
            os.environ,
            {
                "MANGA_WATCH_WATCHLIST": str(watchlist_path),
                "MANGA_WATCH_STATE": str(state_path),
                "MANGA_WATCH_STORAGE_BACKEND": "json",
                "WEB_ADMIN_MACHINE_AUTH_MODE": "google_oidc",
                "WEB_ADMIN_MACHINE_AUTH_AUDIENCE": "https://comic-crawler-web.run.app",
                "WEB_ADMIN_MACHINE_AUTH_PRINCIPALS": "svc@example.com",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_api_rejects_missing_bearer_token(self):
        response = self.client.get("/api/watchlist/")
        self.assertEqual(401, response.status_code)

    def test_api_returns_watchlist_for_valid_machine_identity(self):
        with mock.patch("web_admin.api.auth.verify_google_oidc_token", return_value={"email": "svc@example.com"}):
            response = self.client.get("/api/watchlist/", HTTP_AUTHORIZATION="Bearer token")

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.content)
        self.assertEqual("work-1", payload["watchlist"]["works"][0]["id"])

    def test_api_write_endpoint_uses_shared_write_command(self):
        with mock.patch("web_admin.api.auth.verify_google_oidc_token", return_value={"email": "svc@example.com"}):
            response = self.client.post(
                "/api/watchlist/work-1/enabled/",
                data=json.dumps({"enabled": False}),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer token",
            )

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.content)
        self.assertEqual("updated", payload["result"]["action"])

    def test_openapi_endpoint_exposes_machine_auth_policy(self):
        with mock.patch("web_admin.api.auth.verify_google_oidc_token", return_value={"email": "svc@example.com"}):
            response = self.client.get("/api/openapi.json", HTTP_AUTHORIZATION="Bearer token")

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.content)
        self.assertEqual("3.1.0", payload["openapi"])
        self.assertEqual("google_oidc", payload["x-machine-auth-policy"]["mode"])
