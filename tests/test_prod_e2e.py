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


if __name__ == "__main__":
    unittest.main()
