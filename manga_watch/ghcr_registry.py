from __future__ import annotations

import requests

from manga_watch.secret_redaction import redact_secret_text

DEFAULT_TIMEOUT = 10
MANIFEST_ACCEPT_HEADERS = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)


def parse_image_tag(image_ref: str) -> tuple[str, str, str]:
    registry, separator, remainder = image_ref.partition("/")
    repository, tag_separator, tag = remainder.rpartition(":")
    if not separator or not repository or not tag_separator or not tag or "@" in image_ref:
        raise ValueError(f"expected tagged image reference, got: {image_ref}")
    return registry, repository, tag


def fetch_registry_token(
    *,
    registry: str,
    repository: str,
    session: requests.Session | None = None,
) -> str:
    if registry != "ghcr.io":
        raise ValueError(f"unsupported registry for public token flow: {registry}")

    client = session or requests.Session()
    try:
        response = client.get(
            f"https://{registry}/token",
            params={
                "scope": f"repository:{repository}:pull",
                "service": registry,
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"GHCR token lookup failed: {redact_secret_text(exc)}") from exc

    if not 200 <= response.status_code < 300:
        detail = redact_secret_text(response.text.strip().replace("\n", " "))
        raise RuntimeError(f"GHCR token lookup returned HTTP {response.status_code}: {detail[:300]}")

    payload = response.json()
    token = payload.get("token") if isinstance(payload, dict) else None
    if not token:
        raise RuntimeError("GHCR token lookup returned no token")
    return str(token)


def resolve_public_tag_digest(
    image_ref: str,
    *,
    session: requests.Session | None = None,
) -> str:
    registry, repository, tag = parse_image_tag(image_ref)
    client = session or requests.Session()
    token = fetch_registry_token(
        registry=registry,
        repository=repository,
        session=client,
    )

    try:
        response = client.get(
            f"https://{registry}/v2/{repository}/manifests/{tag}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": ",".join(MANIFEST_ACCEPT_HEADERS),
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "GHCR manifest lookup failed: "
            f"{redact_secret_text(exc, secrets=(token,))}"
        ) from exc

    if not 200 <= response.status_code < 300:
        detail = redact_secret_text(
            response.text.strip().replace("\n", " "),
            secrets=(token,),
        )
        raise RuntimeError(f"GHCR manifest lookup returned HTTP {response.status_code}: {detail[:300]}")

    digest = str(response.headers.get("Docker-Content-Digest", "")).strip()
    if not digest:
        raise RuntimeError("GHCR manifest lookup returned no Docker-Content-Digest header")
    return digest
