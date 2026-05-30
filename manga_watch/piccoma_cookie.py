from __future__ import annotations

import os
from typing import Mapping, Optional, Protocol
from urllib.parse import urlparse

from manga_watch.secret_resolver import build_secret_manager_client, resolve_env_value

PICCOMA_COOKIE_ENV = "PICCOMA_COOKIE"
PICCOMA_COOKIE_SECRET_NAME_ENV = "PICCOMA_COOKIE_SECRET_NAME"
PICCOMA_COOKIE_SECRET_VERSION_ENV = "PICCOMA_COOKIE_SECRET_VERSION"


class PiccomaCookieSaveError(RuntimeError):
    pass


class SecretVersionClient(Protocol):
    def add_secret_version(self, request: Mapping[str, object]) -> object:
        ...


def resolve_piccoma_cookie(
    *,
    environ: Optional[Mapping[str, str]] = None,
    secret_resolver=resolve_env_value,
) -> Optional[str]:
    return secret_resolver(PICCOMA_COOKIE_ENV, environ=environ)


def piccoma_cookie_headers_for_url(url: str, cookie_header: Optional[str]) -> dict[str, str]:
    cookie = str(cookie_header or "").strip()
    if not cookie:
        return {}
    host = (urlparse(url).hostname or "").lower()
    if host not in {"piccoma.com", "www.piccoma.com"}:
        return {}
    return {"Cookie": cookie}


def save_piccoma_cookie_secret(
    cookie_header: str,
    *,
    environ: Optional[Mapping[str, str]] = None,
    client: Optional[SecretVersionClient] = None,
) -> None:
    cookie = _validated_cookie_header(cookie_header)
    secret_name = _piccoma_cookie_secret_name(environ=environ)
    resolved_client = client or build_secret_manager_client()
    resolved_client.add_secret_version(
        request={
            "parent": secret_name,
            "payload": {"data": cookie.encode("utf-8")},
        }
    )


def _validated_cookie_header(cookie_header: str) -> str:
    cookie = str(cookie_header or "").strip()
    if not cookie:
        raise PiccomaCookieSaveError("Piccoma cookie is empty")
    if "\n" in cookie or "\r" in cookie:
        raise PiccomaCookieSaveError("Piccoma cookie must be a single line")
    if "=" not in cookie:
        raise PiccomaCookieSaveError("Piccoma cookie must be a Cookie header")
    return cookie


def _piccoma_cookie_secret_name(*, environ: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if environ is None else environ
    direct_name = str(env.get(PICCOMA_COOKIE_SECRET_NAME_ENV) or "").strip()
    if direct_name:
        return direct_name

    secret_version = str(env.get(PICCOMA_COOKIE_SECRET_VERSION_ENV) or "").strip()
    marker = "/versions/"
    if marker in secret_version:
        return secret_version.split(marker, maxsplit=1)[0]

    raise PiccomaCookieSaveError(
        f"{PICCOMA_COOKIE_SECRET_NAME_ENV} or {PICCOMA_COOKIE_SECRET_VERSION_ENV} is required"
    )
