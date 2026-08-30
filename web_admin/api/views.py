from __future__ import annotations

import json
from typing import Any, Dict

from django.http import HttpRequest, HttpResponseNotAllowed, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from manga_watch.watchlist import WatchlistAddError
from web_admin.operations import commands, queries
from web_admin.operations.codex_approvals import ApprovalRequestError

from .auth import machine_auth_required
from .openapi import build_openapi_schema


class ApiRequestError(ValueError):
    pass


def _json_body(request: HttpRequest) -> Dict[str, Any]:
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ApiRequestError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ApiRequestError("request body must be a JSON object")
    return payload


def _json_request_error_response(exc: ApiRequestError) -> JsonResponse:
    return JsonResponse({"ok": False, "error": str(exc)}, status=400)


def _watchlist_error_response(exc: WatchlistAddError) -> JsonResponse:
    status = 404 if exc.kind == "missing_work" else 400
    payload = {"ok": False, "error": exc.message, "detail": exc.to_dict()}
    return JsonResponse(payload, status=status)


def _approval_error_response(exc: ApprovalRequestError) -> JsonResponse:
    return JsonResponse({"ok": False, "error": str(exc)}, status=400)


def _boolean_field(payload: Dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ApiRequestError(f"{key} must be a boolean")
    return value


@machine_auth_required
@csrf_exempt
def watchlist_collection(request: HttpRequest):
    if request.method == "GET":
        return JsonResponse({"ok": True, "watchlist": queries.get_watchlist_data()})
    if request.method == "POST":
        try:
            payload = _json_body(request)
            result = commands.add_watchlist_url_command(str(payload.get("url") or ""))
        except ApiRequestError as exc:
            return _json_request_error_response(exc)
        except WatchlistAddError as exc:
            return _watchlist_error_response(exc)
        return JsonResponse({"ok": True, "result": result})
    return HttpResponseNotAllowed(["GET", "POST"])


@machine_auth_required
def state_detail(request: HttpRequest):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse({"ok": True, "state": queries.get_state_data()})


@machine_auth_required
def health_detail(request: HttpRequest):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse({"ok": True, "health": queries.get_health_report()})


@machine_auth_required
def capabilities_detail(request: HttpRequest):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse({"ok": True, "capabilities": queries.get_capabilities()})


@machine_auth_required
def run_history_detail(request: HttpRequest):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse({"ok": True, "run_history": queries.get_run_history()})


@csrf_exempt
@machine_auth_required
def watchlist_enabled_detail(request: HttpRequest, work_id: str):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        payload = _json_body(request)
        enabled = _boolean_field(payload, "enabled")
        result = commands.update_watchlist_work_command(work_id, enabled=enabled)
    except ApiRequestError as exc:
        return _json_request_error_response(exc)
    except WatchlistAddError as exc:
        return _watchlist_error_response(exc)
    return JsonResponse({"ok": True, "result": result})


@csrf_exempt
@machine_auth_required
def manual_run_detail(request: HttpRequest):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    return JsonResponse({"ok": True, "result": commands.trigger_manual_run_command()})


@csrf_exempt
@machine_auth_required
def codex_approval_assess_detail(request: HttpRequest):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        payload = _json_body(request)
        result = queries.assess_codex_approval(payload)
    except ApiRequestError as exc:
        return _json_request_error_response(exc)
    except ApprovalRequestError as exc:
        return _approval_error_response(exc)
    return JsonResponse(result)


@machine_auth_required
def openapi_detail(request: HttpRequest):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse(build_openapi_schema())
