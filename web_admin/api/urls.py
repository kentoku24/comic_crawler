from __future__ import annotations

from django.urls import path

from . import views


app_name = "api"

urlpatterns = [
    path("watchlist/", views.watchlist_collection, name="watchlist"),
    path("state/", views.state_detail, name="state"),
    path("health/", views.health_detail, name="health"),
    path("capabilities/", views.capabilities_detail, name="capabilities"),
    path("run-history/", views.run_history_detail, name="run_history"),
    path("watchlist/<str:work_id>/enabled/", views.watchlist_enabled_detail, name="watchlist_enabled"),
    path("manual-run/", views.manual_run_detail, name="manual_run"),
    path("codex/approval-assess/", views.codex_approval_assess_detail, name="codex_approval_assess"),
    path("openapi.json", views.openapi_detail, name="openapi"),
]
