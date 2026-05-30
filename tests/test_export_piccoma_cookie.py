import importlib.util
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path


def load_cookie_helper_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "export_piccoma_cookie.py"
    if not script_path.exists():
        raise AssertionError(f"missing Piccoma cookie helper script: {script_path}")

    spec = importlib.util.spec_from_file_location("export_piccoma_cookie", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load import spec for: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExportPiccomaCookieTests(unittest.TestCase):
    def test_is_piccoma_cookie_host_accepts_only_expected_hosts(self):
        module = load_cookie_helper_module()

        self.assertTrue(module.is_piccoma_cookie_host("piccoma.com"))
        self.assertTrue(module.is_piccoma_cookie_host(".piccoma.com"))
        self.assertTrue(module.is_piccoma_cookie_host("www.piccoma.com"))
        self.assertTrue(module.is_piccoma_cookie_host("WWW.PICCOMA.COM"))

        self.assertFalse(module.is_piccoma_cookie_host("api.piccoma.com"))
        self.assertFalse(module.is_piccoma_cookie_host("notpiccoma.com"))
        self.assertFalse(module.is_piccoma_cookie_host("piccoma.com.example"))

    def test_format_cookie_header_joins_names_and_values_without_logging_context(self):
        module = load_cookie_helper_module()

        cookies = [
            module.ExportedCookie(name="sessionid", value="secret-one"),
            module.ExportedCookie(name="csrf", value="secret-two"),
        ]

        self.assertEqual("sessionid=secret-one; csrf=secret-two", module.format_cookie_header(cookies))

    def test_cookie_db_for_profile_prefers_network_cookies(self):
        module = load_cookie_helper_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            profile = Path(tmpdir)
            legacy_db = profile / "Cookies"
            network_dir = profile / "Network"
            network_dir.mkdir()
            network_db = network_dir / "Cookies"
            legacy_db.write_text("", encoding="utf-8")
            network_db.write_text("", encoding="utf-8")

            self.assertEqual(network_db, module.cookie_db_for_profile(profile))

    def test_read_piccoma_cookies_from_db_uses_plaintext_values_and_filters_hosts(self):
        module = load_cookie_helper_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            cookie_db = Path(tmpdir) / "Cookies"
            connection = sqlite3.connect(cookie_db)
            try:
                connection.execute(
                    """
                    CREATE TABLE cookies (
                        host_key TEXT NOT NULL,
                        name TEXT NOT NULL,
                        value TEXT NOT NULL,
                        encrypted_value BLOB NOT NULL,
                        path TEXT NOT NULL,
                        expires_utc INTEGER NOT NULL,
                        creation_utc INTEGER NOT NULL
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO cookies (
                        host_key, name, value, encrypted_value, path, expires_utc, creation_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (".piccoma.com", "sessionid", "secret-one", b"", "/", 0, 2),
                        ("www.piccoma.com", "csrf", "secret-two", b"", "/", 0, 1),
                        ("example.com", "ignored", "secret-three", b"", "/", 0, 3),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            cookies = module.read_piccoma_cookies_from_db(cookie_db)

        self.assertEqual(
            [
                module.ExportedCookie(name="csrf", value="secret-two"),
                module.ExportedCookie(name="sessionid", value="secret-one"),
            ],
            cookies,
        )

    def test_unsupported_encrypted_cookie_error_does_not_include_cookie_value(self):
        module = load_cookie_helper_module()
        original_platform = module.sys.platform
        module.sys.platform = "darwin"
        try:
            with self.assertRaises(module.CookieExportError) as context:
                module.decrypt_chromium_cookie_value(
                    b"secret-cookie-value",
                    cookie_name="sessionid",
                )
        finally:
            module.sys.platform = original_platform

        self.assertIn("unsupported Chrome encrypted_value format", str(context.exception))
        self.assertNotIn("secret-cookie-value", str(context.exception))

    def test_decode_cookie_value_strips_chrome_host_digest_for_newer_db_versions(self):
        module = load_cookie_helper_module()
        host_key = ".piccoma.com"
        host_digest = hashlib.sha256(host_key.encode("utf-8")).digest().decode("latin1")
        raw_cookie = module.RawCookie(
            host_key=host_key,
            name="sessionid",
            value=f"{host_digest}secret-one",
            encrypted_value=b"",
            expires_utc=0,
        )

        self.assertEqual(
            "secret-one",
            module.decode_cookie_value_for_cookie(raw_cookie, db_version=24),
        )


if __name__ == "__main__":
    unittest.main()
