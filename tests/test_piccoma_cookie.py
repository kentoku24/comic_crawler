import unittest

from manga_watch.piccoma_cookie import (
    PiccomaCookieSaveError,
    piccoma_cookie_headers_for_url,
    save_piccoma_cookie_secret,
)


class FakeSecretManagerClient:
    def __init__(self):
        self.requests = []

    def add_secret_version(self, request):
        self.requests.append(request)


class PiccomaCookieTests(unittest.TestCase):
    def test_piccoma_cookie_headers_apply_only_to_piccoma_hosts(self):
        cookie = "sessionid=secret-one; csrf=secret-two"

        self.assertEqual(
            {"Cookie": cookie},
            piccoma_cookie_headers_for_url("https://piccoma.com/web/product/1", cookie),
        )
        self.assertEqual(
            {"Cookie": cookie},
            piccoma_cookie_headers_for_url("https://www.piccoma.com/web/product/1", cookie),
        )
        self.assertEqual(
            {},
            piccoma_cookie_headers_for_url("https://example.com/web/product/1", cookie),
        )

    def test_save_piccoma_cookie_secret_adds_version_without_logging_cookie(self):
        client = FakeSecretManagerClient()

        save_piccoma_cookie_secret(
            "sessionid=secret-one; csrf=secret-two",
            environ={"PICCOMA_COOKIE_SECRET_NAME": "projects/demo/secrets/piccoma-cookie"},
            client=client,
        )

        self.assertEqual("projects/demo/secrets/piccoma-cookie", client.requests[0]["parent"])
        self.assertEqual(
            b"sessionid=secret-one; csrf=secret-two",
            client.requests[0]["payload"]["data"],
        )

    def test_save_piccoma_cookie_secret_rejects_multiline_value(self):
        with self.assertRaises(PiccomaCookieSaveError) as context:
            save_piccoma_cookie_secret(
                "sessionid=secret-one\ncsrf=secret-two",
                environ={"PICCOMA_COOKIE_SECRET_NAME": "projects/demo/secrets/piccoma-cookie"},
                client=FakeSecretManagerClient(),
            )

        self.assertNotIn("secret-one", str(context.exception))


if __name__ == "__main__":
    unittest.main()
