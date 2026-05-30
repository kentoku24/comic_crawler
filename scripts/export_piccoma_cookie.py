#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, NamedTuple

PICCOMA_COOKIE_HOSTS = frozenset({"piccoma.com", ".piccoma.com", "www.piccoma.com"})
CHROME_COOKIE_EPOCH_OFFSET_MICROSECONDS = 11644473600 * 1_000_000
CHROME_KEYCHAIN_SERVICE = "Chrome Safe Storage"
CHROME_KEYCHAIN_ACCOUNT = "Chrome"
CHROMIUM_MAC_SALT = b"saltysalt"
CHROMIUM_MAC_IV = b" " * 16
CHROMIUM_MAC_KEY_LENGTH = 16
CHROMIUM_MAC_KEY_ITERATIONS = 1003


class CookieExportError(RuntimeError):
    pass


class ExportedCookie(NamedTuple):
    name: str
    value: str


class RawCookie(NamedTuple):
    host_key: str
    name: str
    value: str
    encrypted_value: bytes | memoryview | None
    expires_utc: int


def is_piccoma_cookie_host(host_key: str) -> bool:
    normalized = host_key.strip().lower()
    if normalized.endswith("."):
        normalized = normalized[:-1]
    return normalized in PICCOMA_COOKIE_HOSTS


def format_cookie_header(cookies: Iterable[ExportedCookie]) -> str:
    return "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookies)


def cookie_db_for_profile(profile_path: Path) -> Path:
    profile_path = profile_path.expanduser()
    network_cookie_db = profile_path / "Network" / "Cookies"
    legacy_cookie_db = profile_path / "Cookies"
    if network_cookie_db.exists():
        return network_cookie_db
    if legacy_cookie_db.exists():
        return legacy_cookie_db
    return network_cookie_db


def default_chrome_profile_dirs(home: Path | None = None) -> list[Path]:
    if home is None:
        home = Path.home()
    chrome_root = home / "Library" / "Application Support" / "Google" / "Chrome"
    default_profile = chrome_root / "Default"
    profile_dirs = []
    if chrome_root.exists():
        profile_dirs = sorted(
            path
            for path in chrome_root.glob("Profile *")
            if path.is_dir()
        )
    return [default_profile, *profile_dirs]


def find_default_chrome_cookie_db() -> Path:
    candidates = [cookie_db_for_profile(profile) for profile in default_chrome_profile_dirs()]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise CookieExportError(
        "could not find a Chrome Cookies database; pass --profile or --cookie-db "
        f"(searched: {searched})"
    )


def resolve_cookie_db(*, profile: str | None, cookie_db: str | None) -> Path:
    if profile and cookie_db:
        raise CookieExportError("pass only one of --profile or --cookie-db")
    if cookie_db:
        return Path(cookie_db).expanduser()
    if profile:
        return cookie_db_for_profile(Path(profile))
    return find_default_chrome_cookie_db()


def chrome_time_now() -> int:
    return int(time.time() * 1_000_000) + CHROME_COOKIE_EPOCH_OFFSET_MICROSECONDS


def is_unexpired_cookie(expires_utc: int, *, now: int | None = None) -> bool:
    if expires_utc == 0:
        return True
    if now is None:
        now = chrome_time_now()
    return expires_utc > now


def read_piccoma_cookies_from_db(cookie_db: Path) -> list[ExportedCookie]:
    cookie_db = cookie_db.expanduser()
    if not cookie_db.exists():
        raise CookieExportError(f"cookie database does not exist: {cookie_db}")

    connection = sqlite3.connect(f"{cookie_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        db_version = read_chrome_cookie_db_version(connection)
        rows = connection.execute(
            """
            SELECT host_key, name, value, encrypted_value, path, expires_utc, creation_utc
            FROM cookies
            ORDER BY creation_utc ASC
            """
        )
        cookies: list[ExportedCookie] = []
        for host_key, name, value, encrypted_value, _path, expires_utc, _creation_utc in rows:
            raw_cookie = RawCookie(
                host_key=str(host_key or ""),
                name=str(name or ""),
                value=str(value or ""),
                encrypted_value=encrypted_value,
                expires_utc=int(expires_utc),
            )
            if not raw_cookie.name:
                continue
            if not is_piccoma_cookie_host(raw_cookie.host_key):
                continue
            if not is_unexpired_cookie(raw_cookie.expires_utc):
                continue
            cookie_value = decode_cookie_value_for_cookie(
                raw_cookie,
                db_version=db_version,
            )
            cookies.append(ExportedCookie(name=raw_cookie.name, value=cookie_value))
        return cookies
    except sqlite3.DatabaseError as exc:
        raise CookieExportError(f"failed to read Chrome Cookies database: {cookie_db}") from exc
    finally:
        connection.close()


def read_chrome_cookie_db_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'version'"
        ).fetchone()
    except sqlite3.DatabaseError:
        return 0
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def decode_cookie_value_for_cookie(cookie: RawCookie, *, db_version: int) -> str:
    value = decode_cookie_value(
        value=cookie.value,
        encrypted_value=cookie.encrypted_value,
        cookie_name=cookie.name,
    )
    if not value or db_version < 24:
        return value

    host_digest = hashlib.sha256(cookie.host_key.encode("utf-8")).digest()
    value_bytes = value.encode("latin1")
    if not value_bytes.startswith(host_digest):
        return value
    return value_bytes[len(host_digest):].decode("utf-8")


def decode_cookie_value(
    *,
    value: str,
    encrypted_value: bytes | memoryview | None,
    cookie_name: str,
) -> str:
    if value:
        return value
    encrypted_bytes = bytes(encrypted_value or b"")
    if not encrypted_bytes:
        return ""
    return decrypt_chromium_cookie_value(encrypted_bytes, cookie_name=cookie_name)


def get_chrome_safe_storage_password() -> str:
    command = [
        "security",
        "find-generic-password",
        "-w",
        "-s",
        CHROME_KEYCHAIN_SERVICE,
        "-a",
        CHROME_KEYCHAIN_ACCOUNT,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CookieExportError("macOS security command is required to decrypt Chrome cookies") from exc

    if result.returncode != 0:
        raise CookieExportError(
            "failed to read Chrome Safe Storage from Keychain; unlock Keychain or use a plaintext cookie DB"
        )
    return result.stdout.rstrip("\n")


def derive_chromium_mac_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha1",
        password.encode("utf-8"),
        CHROMIUM_MAC_SALT,
        CHROMIUM_MAC_KEY_ITERATIONS,
        dklen=CHROMIUM_MAC_KEY_LENGTH,
    )


def decrypt_chromium_cookie_value(encrypted_value: bytes, *, cookie_name: str) -> str:
    if sys.platform != "darwin":
        raise CookieExportError("encrypted Chrome cookies are only supported on macOS by this helper")
    if not (encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11")):
        raise CookieExportError(
            f"cookie {cookie_name!r} uses an unsupported Chrome encrypted_value format"
        )

    key = derive_chromium_mac_key(get_chrome_safe_storage_password())
    return decrypt_aes_128_cbc_with_openssl(
        encrypted_value[3:],
        key=key,
        cookie_name=cookie_name,
    )


def decrypt_aes_128_cbc_with_openssl(ciphertext: bytes, *, key: bytes, cookie_name: str) -> str:
    command = [
        "openssl",
        "enc",
        "-d",
        "-aes-128-cbc",
        "-K",
        key.hex(),
        "-iv",
        CHROMIUM_MAC_IV.hex(),
    ]
    try:
        result = subprocess.run(
            command,
            input=ciphertext,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CookieExportError("openssl is required to decrypt Chrome cookies") from exc

    if result.returncode != 0:
        raise CookieExportError(f"failed to decrypt cookie {cookie_name!r}")
    return result.stdout.decode("latin1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export Piccoma cookies from a local Chrome profile as one Cookie header. "
            "The cookie value is written only to stdout."
        ),
    )
    parser.add_argument(
        "--profile",
        help="Chrome profile directory, e.g. ~/Library/Application Support/Google/Chrome/Default",
    )
    parser.add_argument(
        "--cookie-db",
        help="Explicit Chrome Cookies SQLite database path. Useful for deterministic usage and tests.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cookie_db = resolve_cookie_db(profile=args.profile, cookie_db=args.cookie_db)
        cookies = read_piccoma_cookies_from_db(cookie_db)
        if not cookies:
            raise CookieExportError("no Piccoma cookies found in the selected Chrome Cookies database")
        print(format_cookie_header(cookies))
        return 0
    except CookieExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    os.environ.pop("PYTHONINSPECT", None)
    raise SystemExit(main())
