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


if __name__ == "__main__":
    unittest.main()
