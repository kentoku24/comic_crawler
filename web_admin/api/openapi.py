from __future__ import annotations

from typing import Dict

from web_admin.operations.capabilities import capability_report


def build_openapi_schema(*, backend: str | None = None) -> Dict[str, object]:
    capabilities = capability_report(backend=backend).to_dict()
    work_id_parameter = {
        "name": "work_id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Watchlist work identifier.",
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "comic_crawler web admin API",
            "version": "0.1.0",
        },
        "paths": {
            "/api/watchlist/": {"get": {"summary": "List watchlist entries"}, "post": {"summary": "Add watchlist entry"}},
            "/api/state/": {"get": {"summary": "Read current state"}},
            "/api/health/": {"get": {"summary": "Read health report"}},
            "/api/capabilities/": {"get": {"summary": "Read backend and auth capabilities"}},
            "/api/run-history/": {"get": {"summary": "Read run history when supported"}},
            "/api/watchlist/{work_id}/enabled/": {
                "post": {
                    "summary": "Enable or disable a work",
                    "parameters": [work_id_parameter],
                }
            },
            "/api/manual-run/": {"post": {"summary": "Trigger a background manual run"}},
        },
        "x-machine-auth-policy": capabilities["machine_auth_policy"],
    }
