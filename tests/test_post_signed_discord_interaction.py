import importlib.util
import json
import unittest
from unittest import mock
from pathlib import Path

from nacl.signing import SigningKey


def load_script_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "post_signed_discord_interaction.py"
    if not script_path.exists():
        raise AssertionError(f"missing helper script: {script_path}")

    spec = importlib.util.spec_from_file_location("post_signed_discord_interaction", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load import spec for: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return self.response


class PostSignedDiscordInteractionTests(unittest.TestCase):
    def test_signed_headers_verify_against_generated_public_key(self):
        module = load_script_module()
        private_key = "11" * 32
        payload = {"type": 1}
        body = module.canonical_body(payload)

        headers = module.signed_headers(
            body=body,
            private_key_hex=private_key,
            timestamp="1700000000",
        )

        verify_key = SigningKey(bytes.fromhex(private_key)).verify_key
        verify_key.verify(
            b"1700000000" + body,
            bytes.fromhex(headers["X-Signature-Ed25519"]),
        )

    def test_post_signed_interaction_sends_compact_json_body(self):
        module = load_script_module()
        session = FakeSession(response=FakeResponse(status_code=401, text="invalid request signature"))

        result = module.post_signed_interaction(
            url="https://example.com/interactions",
            payload={"type": 2, "data": {"name": "latest"}},
            private_key_hex="11" * 32,
            timestamp="1700000000",
            invalidate_signature=True,
            session=session,
        )

        self.assertEqual(401, result["statusCode"])
        self.assertEqual("invalid request signature", result["body"])
        self.assertEqual(
            b'{"type":2,"data":{"name":"latest"}}',
            session.posts[0]["data"],
        )
        self.assertEqual("1700000000", session.posts[0]["headers"]["X-Signature-Timestamp"])

    def test_main_returns_non_zero_when_expected_status_mismatches(self):
        module = load_script_module()
        session = FakeSession(response=FakeResponse(status_code=401, text="unauthorized"))

        with mock.patch("requests.Session", return_value=session):
            exit_code = module.main(
                [
                    "--url",
                    "https://example.com/interactions",
                    "--private-key",
                    "11" * 32,
                    "--payload-json",
                    json.dumps({"type": 1}),
                    "--expect-status",
                    "200",
                ]
            )

        self.assertEqual(1, exit_code)


if __name__ == "__main__":
    unittest.main()
