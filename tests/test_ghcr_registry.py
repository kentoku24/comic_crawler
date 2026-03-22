import unittest

from manga_watch.ghcr_registry import resolve_public_tag_digest


class FakeResponse:
    def __init__(self, status_code, *, headers=None, json_body=None, text=""):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self._json_body = json_body
        self.text = text

    def json(self):
        return self._json_body


class FakeSession:
    def __init__(self, *, get_responses=None):
        self.get_responses = list(get_responses or [])
        self.calls = []

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if not self.get_responses:
            raise AssertionError("unexpected GHCR request")
        return self.get_responses.pop(0)


class GhcrRegistryTests(unittest.TestCase):
    def test_resolve_public_tag_digest_fetches_bearer_token_then_manifest_digest(self):
        session = FakeSession(
            get_responses=[
                FakeResponse(200, json_body={"token": "token-123"}),
                FakeResponse(200, headers={"Docker-Content-Digest": "sha256:d1"}),
            ]
        )

        digest = resolve_public_tag_digest(
            "ghcr.io/kentoku24/comic_crawler:latest",
            session=session,
        )

        self.assertEqual("sha256:d1", digest)
        self.assertEqual(
            "https://ghcr.io/token",
            session.calls[0]["url"],
        )
        self.assertEqual(
            {
                "scope": "repository:kentoku24/comic_crawler:pull",
                "service": "ghcr.io",
            },
            session.calls[0]["params"],
        )
        self.assertEqual(
            "https://ghcr.io/v2/kentoku24/comic_crawler/manifests/latest",
            session.calls[1]["url"],
        )
        self.assertEqual("Bearer token-123", session.calls[1]["headers"]["Authorization"])

    def test_resolve_public_tag_digest_accepts_oci_image_index_manifests(self):
        session = FakeSession(
            get_responses=[
                FakeResponse(200, json_body={"token": "token-123"}),
                FakeResponse(200, headers={"Docker-Content-Digest": "sha256:d1"}),
            ]
        )

        resolve_public_tag_digest(
            "ghcr.io/kentoku24/comic_crawler:latest",
            session=session,
        )

        self.assertIn(
            "application/vnd.oci.image.index.v1+json",
            session.calls[1]["headers"]["Accept"],
        )

    def test_resolve_public_tag_digest_raises_when_digest_header_missing(self):
        session = FakeSession(
            get_responses=[
                FakeResponse(200, json_body={"token": "token-123"}),
                FakeResponse(200, headers={}),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "Docker-Content-Digest"):
            resolve_public_tag_digest(
                "ghcr.io/kentoku24/comic_crawler:latest",
                session=session,
            )
