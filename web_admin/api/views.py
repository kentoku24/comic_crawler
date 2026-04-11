from __future__ import annotations

import json
from typing import Any, Dict

from django.http import HttpRequest, HttpResponseNotAllowed, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from web_admin.operations import commands, queries

from .auth import machine_auth_required
from .openapi import build_openapi_schema


def _json_body(request: HttpRequest) -> Dict[str, Any]:
    if not request.body:
        return {}
    return json.loads(request.body.decode("utf-8"))


@machine_auth_required
def watchlist_collection(request: HttpRequest):
    if request.method == "GET":
        return JsonResponse({"ok": True, "watchlist": queries.get_watchlist_data()})
    if request.method == "POST":
        payload = _json_body(request)
        result = commands.add_watchlist_url_command(str(payload.get("url") or ""))
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
    payload = _json_body(request)
    result = commands.update_watchlist_work_command(work_id, enabled=bool(payload.get("enabled")))
    return JsonResponse({"ok": True, "result": result})


@csrf_exempt
@machine_auth_required
def manual_run_detail(request: HttpRequest):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    return JsonResponse({"ok": True, "result": commands.trigger_manual_run_command()})


@machine_auth_required
def openapi_detail(request: HttpRequest):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse(build_openapi_schema())
