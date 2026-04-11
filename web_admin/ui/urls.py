from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


app_name = "ui"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(template_name="ui/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("watchlist/add/", views.add_watchlist_entry, name="add_watchlist_entry"),
    path("watchlist/enabled/", views.update_work_enabled, name="update_work_enabled"),
    path("manual-run/", views.trigger_manual_run, name="trigger_manual_run"),
]
