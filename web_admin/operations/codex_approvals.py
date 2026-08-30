from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional


READ_ONLY_HINTS = (
    "cat ",
    "head ",
    "tail ",
    "less ",
    "more ",
    "grep ",
    "find ",
    "ls",
    "pwd",
    "git status",
    "git diff",
    "git show",
)

WRITE_HINTS = (
    "rm ",
    "mv ",
    "cp ",
    "sed -i",
    "perl -i",
    "tee ",
    ">",
    ">>",
    "chmod ",
    "chown ",
    "git commit",
    "git push",
    "docker ",
    "kubectl ",
    "gcloud ",
    "terraform ",
)

NETWORK_HINTS = (
    "curl ",
    "wget ",
    "scp ",
    "rsync ",
    "gh api",
    "git push",
)

PRIVILEGE_HINTS = (
    "sudo ",
    "su ",
    "doas ",
)

SECRET_HINTS = (
    ".env",
    "id_rsa",
    "id_ed25519",
    "secret",
    "token",
    "password",
    "private key",
    "oauth",
)

DESTRUCTIVE_HINTS = (
    "rm -rf",
    "mkfs",
    "dd ",
    "shutdown",
    "reboot",
    "systemctl stop",
    "drop table",
)


@dataclass(frozen=True)
class ApprovalAssessment:
    summary: str
    recommendation: str
    risk_level: str
    requires_human_attention: bool
    categories: List[str]
    reasons: List[str]
    allow_reasons: List[str]
    deny_reasons: List[str]
    command: str
    working_directory: Optional[str] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalRequest:
    command: str
    working_directory: Optional[str] = None
    source: Optional[str] = None
    justification: Optional[str] = None


class ApprovalRequestError(ValueError):
    pass


def parse_approval_request(payload: Mapping[str, object]) -> ApprovalRequest:
    command = str(payload.get("command") or "").strip()
    if not command:
        raise ApprovalRequestError("command is required")
    working_directory = payload.get("working_directory")
    source = payload.get("source")
    justification = payload.get("justification")
    return ApprovalRequest(
        command=command,
        working_directory=str(working_directory) if isinstance(working_directory, str) and working_directory.strip() else None,
        source=str(source) if isinstance(source, str) and source.strip() else None,
        justification=str(justification) if isinstance(justification, str) and justification.strip() else None,
    )


def assess_approval_request(request: ApprovalRequest) -> ApprovalAssessment:
    command = request.command.strip()
    lower = command.lower()

    categories: List[str] = []
    reasons: List[str] = []
    allow_reasons: List[str] = []
    deny_reasons: List[str] = []

    def mark(category: str, reason: str) -> None:
        if category not in categories:
            categories.append(category)
        reasons.append(reason)

    for hint in READ_ONLY_HINTS:
        if hint in lower:
            mark("read_only", f"read-only っぽい操作を含む: `{hint.strip()}`")
            allow_reasons.append("内容確認や調査目的の読み取り操作に見える")
            break

    for hint in WRITE_HINTS:
        if hint in lower:
            mark("write", f"ファイル変更または外部状態変更の可能性がある: `{hint.strip()}`")
            deny_reasons.append("ファイル・git・infra の状態を変更する可能性がある")
            break

    for hint in NETWORK_HINTS:
        if hint in lower:
            mark("network", f"ネットワーク通信を伴う可能性がある: `{hint.strip()}`")
            deny_reasons.append("外部送信やリモート変更が起きうる")
            break

    for hint in PRIVILEGE_HINTS:
        if hint in lower:
            mark("privilege", f"昇格権限を要求する可能性がある: `{hint.strip()}`")
            deny_reasons.append("権限昇格は影響範囲が大きい")
            break

    for hint in SECRET_HINTS:
        if hint in lower:
            mark("secret", f"秘密情報や認証情報に触れる可能性がある: `{hint}`")
            deny_reasons.append("秘密情報の閲覧・送信につながる可能性がある")
            break

    for hint in DESTRUCTIVE_HINTS:
        if hint in lower:
            mark("destructive", f"破壊的な操作の兆候がある: `{hint.strip()}`")
            deny_reasons.append("復旧が面倒、または不可逆の可能性がある")
            break

    pipeline_markers = ["&&", "||", "|", ";"]
    if any(marker in command for marker in pipeline_markers):
        mark("compound", "複合コマンドで実行内容の影響範囲が広い")
        deny_reasons.append("一度の許可で複数の操作が走る")

    if not categories:
        categories.append("unknown")
        reasons.append("既知ルールに当てはまらず、目的と副作用を追加確認したい")
        deny_reasons.append("未知コマンドなので、そのまま許可するには情報が足りない")

    if "destructive" in categories or "privilege" in categories or "secret" in categories:
        risk_level = "high"
        recommendation = "deny_or_inspect"
    elif "network" in categories or "write" in categories or "compound" in categories:
        risk_level = "medium"
        recommendation = "inspect_before_allow"
    elif categories == ["read_only"]:
        risk_level = "low"
        recommendation = "likely_allow"
    else:
        risk_level = "medium"
        recommendation = "inspect_before_allow"

    if request.justification:
        allow_reasons.append(f"Codex 側の説明: {request.justification}")

    summary = _build_summary(command=command, categories=categories, risk_level=risk_level)
    return ApprovalAssessment(
        summary=summary,
        recommendation=recommendation,
        risk_level=risk_level,
        requires_human_attention=risk_level != "low",
        categories=categories,
        reasons=_dedupe(reasons),
        allow_reasons=_dedupe(allow_reasons),
        deny_reasons=_dedupe(deny_reasons),
        command=command,
        working_directory=request.working_directory,
        source=request.source,
    )


def _build_summary(*, command: str, categories: List[str], risk_level: str) -> str:
    preview = command if len(command) <= 120 else command[:117] + "..."
    labels = ", ".join(categories)
    return f"risk={risk_level}; categories={labels}; command={preview}"


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
