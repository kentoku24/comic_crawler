from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict

from django.http import JsonResponse
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from web_admin.operations.capabilities import machine_auth_policy_from_env


def verify_google_oidc_token(token: str, *, audience: str) -> Dict[str, Any]:
    return dict(id_token.verify_oauth2_token(token, Request(), audience=audience))


def machine_auth_required(view_func: Callable):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        policy = machine_auth_policy_from_env()
        if policy.mode == "disabled":
            request.machine_identity = {"mode": "disabled"}
            return view_func(request, *args, **kwargs)

        auth_header = str(request.headers.get("Authorization") or "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse({"ok": False, "error": "missing bearer token"}, status=401)

        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            return JsonResponse({"ok": False, "error": "missing bearer token"}, status=401)

        try:
            claims = verify_google_oidc_token(token, audience=policy.audience)
        except Exception as exc:  # pragma: no cover - exercised via mocks
            return JsonResponse({"ok": False, "error": f"invalid oidc token: {exc}"}, status=401)

        principal = str(claims.get("email") or claims.get("sub") or "").strip()
        if policy.principals and principal not in policy.principals:
            return JsonResponse({"ok": False, "error": "principal is not allowed"}, status=403)

        request.machine_identity = {
            "principal": principal,
            "claims": claims,
        }
        return view_func(request, *args, **kwargs)

    return wrapped
