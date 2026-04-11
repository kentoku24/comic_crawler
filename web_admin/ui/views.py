from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from manga_watch.watchlist import WatchlistAddError
from web_admin.operations import commands, queries

from .forms import AddWatchlistForm, ManualRunForm, UpdateWorkEnabledForm


@login_required
def dashboard(request):
    context = queries.get_dashboard_snapshot()
    context["add_watchlist_form"] = AddWatchlistForm()
    context["manual_run_form"] = ManualRunForm()
    context["update_forms"] = {
        entry["id"]: UpdateWorkEnabledForm(
            initial={
                "work_id": entry["id"],
                "enabled": entry.get("enabled", False),
            }
        )
        for entry in context["watchlist"]["works"]
    }
    return render(request, "ui/dashboard.html", context)


@login_required
def add_watchlist_entry(request):
    if request.method != "POST":
        return redirect("ui:dashboard")
    form = AddWatchlistForm(request.POST)
    if not form.is_valid():
        messages.error(request, "有効な URL を入力してください。")
        return redirect("ui:dashboard")
    try:
        result = commands.add_watchlist_url_command(form.cleaned_data["url"])
    except WatchlistAddError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f"watchlist action={result['action']}")
    return redirect("ui:dashboard")


@login_required
def update_work_enabled(request):
    if request.method != "POST":
        return redirect("ui:dashboard")
    form = UpdateWorkEnabledForm(request.POST)
    if not form.is_valid():
        messages.error(request, "enabled 更新リクエストが不正です。")
        return redirect("ui:dashboard")
    try:
        commands.update_watchlist_work_command(
            form.cleaned_data["work_id"],
            enabled=bool(form.cleaned_data["enabled"]),
        )
    except WatchlistAddError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f"{form.cleaned_data['work_id']} updated")
    return redirect("ui:dashboard")


@login_required
def trigger_manual_run(request):
    if request.method != "POST":
        return redirect("ui:dashboard")
    form = ManualRunForm(request.POST)
    if not form.is_valid():
        messages.error(request, "manual run request is invalid")
        return redirect("ui:dashboard")
    result = commands.trigger_manual_run_command()
    messages.success(request, f"manual run accepted={result.get('accepted', False)}")
    return redirect("ui:dashboard")
