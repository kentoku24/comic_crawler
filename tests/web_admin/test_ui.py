from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from manga_watch.storage import save_state, save_watchlist


@override_settings(ROOT_URLCONF="web_admin.project.urls")
class UiTests(TestCase):
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
                "WEB_ADMIN_MACHINE_AUTH_PRINCIPALS": "svc@example.com,operator@example.com",
                "WEB_ADMIN_MACHINE_AUTH_INVOKER_ROLE": "roles/run.invoker",
                "WEB_ADMIN_MACHINE_AUTH_WIF_PROVIDER": "projects/123/locations/global/workloadIdentityPools/pool/providers/provider",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_dashboard_requires_login(self):
        response = self.client.get("/ui/")
        self.assertEqual(302, response.status_code)
        self.assertIn("/ui/login/", response["Location"])

    def test_dashboard_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username="operator", password="secret-pass")
        self.client.force_login(user)

        response = self.client.get("/ui/")

        self.assertEqual(200, response.status_code)
        self.assertContains(response, "comic_crawler web admin")
        self.assertContains(response, "work-1")
        self.assertContains(response, "google_oidc")
        self.assertContains(response, "https://comic-crawler-web.run.app")
        self.assertContains(response, "svc@example.com, operator@example.com")
        self.assertContains(response, "roles/run.invoker")
        self.assertContains(
            response,
            "projects/123/locations/global/workloadIdentityPools/pool/providers/provider",
        )

    def test_ui_can_toggle_enabled_without_machine_credentials(self):
        user = get_user_model().objects.create_user(username="operator2", password="secret-pass")
        self.client.force_login(user)

        response = self.client.post(
            "/ui/watchlist/enabled/",
            data={"work_id": "work-1", "enabled": ""},
            follow=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertContains(response, "work-1 updated")
