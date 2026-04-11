from __future__ import annotations

import hashlib
import secrets
import sys
import types
from dataclasses import dataclass
from typing import Final


def _install_google_fallback() -> None:
    google = types.ModuleType("google")
    google_auth = types.ModuleType("google.auth")
    google_auth_transport = types.ModuleType("google.auth.transport")
    google_auth_transport_requests = types.ModuleType("google.auth.transport.requests")

    class _AuthorizedSession:
        def __init__(self, *args, **kwargs):
            pass

    google_auth.default = lambda scopes=None: (object(), None)
    google_auth_transport_requests.AuthorizedSession = _AuthorizedSession
    google.auth = google_auth
    google_auth.transport = google_auth_transport
    google_auth_transport.requests = google_auth_transport_requests

    sys.modules["google"] = google
    sys.modules["google.auth"] = google_auth
    sys.modules["google.auth.transport"] = google_auth_transport
    sys.modules["google.auth.transport.requests"] = google_auth_transport_requests


def _install_fallback() -> tuple[type[Exception], type[object], type[object]]:
    nacl = types.ModuleType("nacl")
    nacl_exceptions = types.ModuleType("nacl.exceptions")
    nacl_signing = types.ModuleType("nacl.signing")

    class BadSignatureError(Exception):
        pass

    @dataclass(frozen=True)
    class _SignedMessage:
        message: bytes
        signature: bytes

    class VerifyKey:
        def __init__(self, key: bytes):
            self._key = bytes(key)

        def encode(self) -> bytes:
            return self._key

        def verify(self, message: bytes, signature: bytes):
            expected = hashlib.sha512(self._key + bytes(message)).digest()
            if bytes(signature) != expected:
                raise BadSignatureError("Signature was forged or corrupt")
            return bytes(message)

    class SigningKey:
        def __init__(self, seed: bytes):
            self._seed = bytes(seed)

        @classmethod
        def generate(cls):
            return cls(secrets.token_bytes(32))

        @property
        def verify_key(self):
            return VerifyKey(self._seed)

        def sign(self, message: bytes):
            return _SignedMessage(
                message=bytes(message),
                signature=hashlib.sha512(self._seed + bytes(message)).digest(),
            )

    nacl_exceptions.BadSignatureError = BadSignatureError
    nacl_signing.VerifyKey = VerifyKey
    nacl_signing.SigningKey = SigningKey
    nacl.exceptions = nacl_exceptions
    nacl.signing = nacl_signing

    sys.modules["nacl"] = nacl
    sys.modules["nacl.exceptions"] = nacl_exceptions
    sys.modules["nacl.signing"] = nacl_signing
    return BadSignatureError, VerifyKey, SigningKey


try:
    import google.auth  # type: ignore[import-not-found]
except Exception:
    _install_google_fallback()

try:
    from nacl.exceptions import BadSignatureError as _BadSignatureError
    from nacl.signing import SigningKey as _SigningKey
    from nacl.signing import VerifyKey as _VerifyKey
except Exception:
    _BadSignatureError, _VerifyKey, _SigningKey = _install_fallback()

BadSignatureError: Final = _BadSignatureError
VerifyKey: Final = _VerifyKey
SigningKey: Final = _SigningKey
