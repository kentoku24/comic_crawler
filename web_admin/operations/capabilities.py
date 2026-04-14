from __future__ import annotations

import os
from typing import Mapping, Optional

from manga_watch.storage import STORAGE_BACKEND_FIRESTORE, storage_backend_from_env

from .schemas import CapabilityReport, MachineAuthPolicy

DEFAULT_MACHINE_AUTH_MODE = "disabled"
SUPPORTED_MACHINE_AUTH_MODES = {"disabled", "google_oidc"}
DEFAULT_INVOKER_ROLE = "roles/run.invoker"


def machine_auth_policy_from_env(
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> MachineAuthPolicy:
    env = os.environ if environ is None else environ
    mode = str(env.get("WEB_ADMIN_MACHINE_AUTH_MODE") or DEFAULT_MACHINE_AUTH_MODE).strip().lower()
    if mode not in SUPPORTED_MACHINE_AUTH_MODES:
        raise ValueError(f"Unsupported WEB_ADMIN_MACHINE_AUTH_MODE: {mode}")

    service_url = str(env.get("WEB_ADMIN_MACHINE_AUTH_SERVICE_URL") or "").strip()
    audience = str(env.get("WEB_ADMIN_MACHINE_AUTH_AUDIENCE") or service_url).strip()
    if mode == "google_oidc" and not audience:
        raise ValueError(
            "WEB_ADMIN_MACHINE_AUTH_AUDIENCE or WEB_ADMIN_MACHINE_AUTH_SERVICE_URL is required "
            "when WEB_ADMIN_MACHINE_AUTH_MODE=google_oidc"
        )

    principals = [
        value.strip()
        for value in str(env.get("WEB_ADMIN_MACHINE_AUTH_PRINCIPALS") or "").split(",")
        if value.strip()
    ]
    return MachineAuthPolicy(
        mode=mode,
        service_private=True,
        allow_static_bearer_token=False,
        google_signed_oidc_required=mode == "google_oidc",
        audience=audience,
        principals=principals,
        invoker_role=str(env.get("WEB_ADMIN_MACHINE_AUTH_INVOKER_ROLE") or DEFAULT_INVOKER_ROLE),
        workload_identity_federation_provider=(
            str(env.get("WEB_ADMIN_MACHINE_AUTH_WIF_PROVIDER") or "").strip() or None
        ),
        service_account=str(env.get("WEB_ADMIN_MACHINE_AUTH_SERVICE_ACCOUNT") or "").strip() or None,
        audit_note=(
            "Cloud Run private service + IAM + short-lived Google-signed OIDC ID token. "
            "Prefer Workload Identity Federation for GCP-external callers."
        ),
    )


def capability_report(*, backend: Optional[str] = None) -> CapabilityReport:
    storage_backend = backend or storage_backend_from_env()
    run_history_supported = storage_backend == STORAGE_BACKEND_FIRESTORE
    run_history_reason = None
    if not run_history_supported:
        run_history_reason = (
            "Run summaries are only persisted when MANGA_WATCH_STORAGE_BACKEND=firestore."
        )
    return CapabilityReport(
        storage_backend=storage_backend,
        run_history_supported=run_history_supported,
        run_history_reason=run_history_reason,
        machine_auth_policy=machine_auth_policy_from_env(),
    )
