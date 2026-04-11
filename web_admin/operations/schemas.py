from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class MachineAuthPolicy:
    mode: str
    service_private: bool
    allow_static_bearer_token: bool
    google_signed_oidc_required: bool
    audience: str
    principals: List[str]
    invoker_role: str
    workload_identity_federation_provider: Optional[str] = None
    service_account: Optional[str] = None
    audit_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityReport:
    storage_backend: str
    run_history_supported: bool
    run_history_reason: Optional[str]
    machine_auth_policy: MachineAuthPolicy

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["machine_auth_policy"] = self.machine_auth_policy.to_dict()
        return payload
