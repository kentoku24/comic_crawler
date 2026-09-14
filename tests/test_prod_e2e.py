import os
import unittest

import requests


class ProductionE2ETests(unittest.TestCase):
    """E2E checks against a deployed environment (Discord UI excluded).

    Required env:
    - MANGA_WATCH_E2E_BASE_URL (e.g. https://<service-url>)
    """

    @classmethod
    def setUpClass(cls):
        cls.base_url = (os.environ.get("MANGA_WATCH_E2E_BASE_URL") or "").rstrip("/")
        cls.bearer_token = (os.environ.get("MANGA_WATCH_E2E_BEARER_TOKEN") or "").strip()
        cls.expected_storage_backend = (
            os.environ.get("MANGA_WATCH_E2E_EXPECTED_STORAGE_BACKEND") or "firestore"
        ).strip()
        cls.expected_work_id = (os.environ.get("MANGA_WATCH_E2E_EXPECTED_WORK_ID") or "").strip()
        if not cls.base_url:
            raise unittest.SkipTest("MANGA_WATCH_E2E_BASE_URL is not set")
        cls.session = requests.Session()

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    def test_healthz_returns_ok(self):
        response = self.session.get(f"{self.base_url}/healthz", timeout=15)
        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.text)

    def test_interaction_rejects_invalid_signature(self):
        response = self.session.post(
            f"{self.base_url}/",
            data=b'{"type":1}',
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": "00" * 64,
                "X-Signature-Timestamp": "1700000000",
            },
            timeout=15,
        )
        self.assertEqual(401, response.status_code)
        self.assertEqual("invalid request signature", response.text)

    def test_api_read_endpoints_require_auth_without_bearer(self):
        read_paths = [
            "/api/watchlist/",
            "/api/state/",
            "/api/health/",
            "/api/capabilities/",
            "/api/run-history/",
            "/api/openapi.json",
        ]
        for path in read_paths:
            with self.subTest(path=path):
                response = self.session.get(f"{self.base_url}{path}", timeout=15)
                self.assertEqual(401, response.status_code)
                self.assertIn("missing bearer token", response.text)

    def test_api_read_endpoints_return_200_with_bearer_token(self):
        if not self.bearer_token:
            raise unittest.SkipTest("MANGA_WATCH_E2E_BEARER_TOKEN is not set")

        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        read_paths = [
            "/api/watchlist/",
            "/api/state/",
            "/api/health/",
            "/api/capabilities/",
            "/api/run-history/",
            "/api/openapi.json",
        ]
        for path in read_paths:
            with self.subTest(path=path):
                response = self.session.get(
                    f"{self.base_url}{path}",
                    headers=headers,
                    timeout=15,
                )
                self.assertEqual(200, response.status_code)

    def test_db_backed_read_returns_expected_content(self):
        """DoD: read request reaches real storage and returns persisted result."""
        if not self.bearer_token:
            raise unittest.SkipTest("MANGA_WATCH_E2E_BEARER_TOKEN is not set")

        headers = {"Authorization": f"Bearer {self.bearer_token}"}

        capabilities = self.session.get(
            f"{self.base_url}/api/capabilities/",
            headers=headers,
            timeout=15,
        )
        self.assertEqual(200, capabilities.status_code)
        capabilities_payload = capabilities.json()
        self.assertTrue(capabilities_payload.get("ok"))
        self.assertEqual(
            self.expected_storage_backend,
            capabilities_payload["capabilities"]["storage_backend"],
        )

        state = self.session.get(
            f"{self.base_url}/api/state/",
            headers=headers,
            timeout=15,
        )
        self.assertEqual(200, state.status_code)
        state_payload = state.json()
        self.assertTrue(state_payload.get("ok"))
        self.assertIsInstance(state_payload.get("state"), dict)
        self.assertIsInstance(state_payload["state"].get("works"), dict)

        watchlist = self.session.get(
            f"{self.base_url}/api/watchlist/",
            headers=headers,
            timeout=15,
        )
        self.assertEqual(200, watchlist.status_code)
        watchlist_payload = watchlist.json()
        self.assertTrue(watchlist_payload.get("ok"))
        self.assertIsInstance(watchlist_payload.get("watchlist"), dict)
        self.assertIsInstance(watchlist_payload["watchlist"].get("works"), list)

        if self.expected_work_id:
            works = watchlist_payload["watchlist"]["works"]
            self.assertTrue(
                any(str(item.get("id")) == self.expected_work_id for item in works),
                msg=f"expected work id not found in watchlist: {self.expected_work_id}",
            )


if __name__ == "__main__":
    unittest.main()
