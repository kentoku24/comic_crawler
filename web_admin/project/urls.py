from __future__ import annotations

from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path("api/", include("web_admin.api.urls")),
    path("ui/", include("web_admin.ui.urls")),
    path("", RedirectView.as_view(pattern_name="ui:dashboard", permanent=False)),
]
