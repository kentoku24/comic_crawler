from __future__ import annotations

import os
from functools import lru_cache
from typing import Mapping, Optional, Protocol


class SecretPayload(Protocol):
    data: bytes


class SecretAccessResponse(Protocol):
    payload: SecretPayload


class SecretManagerClient(Protocol):
    def access_secret_version(self, request: Mapping[str, str]) -> SecretAccessResponse:
        ...


@lru_cache(maxsize=1)
def _cached_secret_manager_client():
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


def build_secret_manager_client():
    return _cached_secret_manager_client()


def resolve_secret_version(
    secret_version: str,
    *,
    client: Optional[SecretManagerClient] = None,
) -> str:
    resolved_client = client or build_secret_manager_client()
    response = resolved_client.access_secret_version(request={"name": secret_version})
    payload = response.payload.data
    return payload.decode("utf-8").strip()


def resolve_env_value(
    env_name: str,
    *,
    environ: Optional[Mapping[str, str]] = None,
    client: Optional[SecretManagerClient] = None,
) -> Optional[str]:
    env = os.environ if environ is None else environ
    direct_value = _coerce_text(env.get(env_name))
    if direct_value is not None:
        return direct_value

    secret_version = _coerce_text(env.get(f"{env_name}_SECRET_VERSION"))
    if secret_version is None:
        return None
    return resolve_secret_version(secret_version, client=client)


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
