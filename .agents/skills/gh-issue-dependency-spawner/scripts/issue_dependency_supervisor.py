#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import issue_dependency_plan as planner


PLAN_SCRIPT = Path(__file__).with_name("issue_dependency_plan.py")
ACTIVE_LEASE_STATES = {
    "spawned",
    "active",
    "waiting_child",
    "reviewer_gate_pending",
    "merge_pending",
    "issue_close_pending",
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_planner(issue_ref: str, repo_override: str | None, ledger_path: Path) -> dict[str, Any]:
    cmd = [sys.executable, str(PLAN_SCRIPT), issue_ref, "--ledger", str(ledger_path)]
    if repo_override:
        cmd.extend(["--repo", repo_override])
    try:
        output = subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as exc:
        message = exc.stderr or exc.stdout or str(exc)
        planner.fail(message.strip())
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        planner.fail(f"planner returned invalid json: {exc}")


def default_ledger_path(issue_ref: str, repo_override: str | None, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    _, _, issue_number = planner.normalize_issue_ref(issue_ref, repo_override)
    return Path(".codex") / "orchestrator-runs" / f"issue-{issue_number}.json"


def write_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def infer_next_transition(action: str) -> str | None:
    mapping = {
        "spawn": "worktree_ready",
        "check_spawn_heartbeat": "worktree_ready",
        "monitor_pr_creation": "pr_opened",
        "monitor_pr": "review_state_changed",
        "resume_rework": "review_state_changed",
        "merge_pr": "merged",
        "resolve_merge_block": "merged",
        "close_issue": "issue_closed",
    }
    return mapping.get(action)


def normalized_lease_state(
    existing: dict[str, Any],
    orchestration_state: str,
    recommended_action: str,
) -> str:
    current = existing.get("lease_state")
    if orchestration_state == "done":
        return "completed"
    if orchestration_state in {"blocked_by_dependencies", "blocked_by_external_dependency"}:
        return "blocked"
    if recommended_action == "spawn":
        return current or "idle"
    if current in ACTIVE_LEASE_STATES:
        return current
    if recommended_action in {"check_spawn_heartbeat", "monitor_pr_creation", "monitor_pr"}:
        return "waiting_child"
    if recommended_action == "resume_rework":
        return "reviewer_gate_pending"
    if recommended_action in {"merge_pr", "resolve_merge_block"}:
        return "merge_pending"
    if recommended_action == "close_issue":
        return "issue_close_pending"
    return current or "idle"


def merge_child_entry(existing: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    entry = dict(existing)
    entry["issue_number"] = child["number"]
    entry["issue_url"] = child["url"]
    entry["issue_title"] = child["title"]
    entry["issue_state"] = child["issue_state"]
    entry["state"] = child["orchestration_state"]
    entry["recommended_parent_action"] = child["recommended_parent_action"]
    entry["recommended_parent_action_reason"] = child["recommended_parent_action_reason"]
    entry["next_expected_transition"] = infer_next_transition(child["recommended_parent_action"])
    entry["blocked_by"] = child["blocked_by"]
    entry["unresolved_blocked_by"] = child["unresolved_blocked_by"]
    entry["blocked_by_external"] = child["blocked_by_external"]
    entry["unresolved_external_blocked_by"] = child["unresolved_external_blocked_by"]
    entry["delivery_evidence_urls"] = child["delivery_evidence_urls"]
    entry["warnings"] = child.get("warnings", [])
    entry["has_dod_section"] = child["has_dod_section"]
    entry["dod_items"] = child["dod_items"]
    entry["closing_pull_requests"] = child["closing_pull_requests"]
    entry["lease_state"] = normalized_lease_state(
        existing,
        child["orchestration_state"],
        child["recommended_parent_action"],
    )
    if child.get("primary_open_pr"):
        entry["pr"] = child["primary_open_pr"]["number"]
        entry["pr_url"] = child["primary_open_pr"]["url"]
    elif child["orchestration_state"] == "done":
        entry.pop("pr", None)
        entry.pop("pr_url", None)
    entry["last_github_reconcile_at"] = utc_now()
    entry["updated_at"] = entry["last_github_reconcile_at"]
    return entry


def sync_ledger(
    existing: dict[str, Any],
    plan: dict[str, Any],
    issue_ref: str,
) -> dict[str, Any]:
    ledger = dict(existing)
    ledger["parent_issue"] = plan["parent"]["url"]
    ledger["parent_issue_ref"] = issue_ref
    ledger["repo"] = plan["parent"]["repo"]
    ledger["run_id"] = ledger.get("run_id") or f"run-{uuid.uuid4().hex[:12]}"
    ledger["tracked_child_numbers"] = plan["tracked_child_numbers"]
    ledger["dependency_edges"] = plan["dependency_edges"]
    ledger["default_branch"] = plan["parent"]["default_branch"]
    ledger["action_groups"] = plan["action_groups"]
    ledger["completion_blockers"] = plan["completion_blockers"]
    ledger["last_plan_at"] = utc_now()
    ledger["updated_at"] = ledger["last_plan_at"]

    existing_children = ledger.get("children") or {}
    synced_children: dict[str, Any] = {}
    for child in plan["children"]:
        key = str(child["number"])
        synced_children[key] = merge_child_entry(existing_children.get(key, {}), child)
    ledger["children"] = synced_children
    return ledger


def apply_github_followups(plan: dict[str, Any], repo: str, dry_run: bool) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for child in plan["children"]:
        action = child["recommended_parent_action"]
        if action == "merge_pr" and child.get("primary_open_pr"):
            pr_number = child["primary_open_pr"]["number"]
            cmd = ["gh", "pr", "merge", str(pr_number), "--repo", repo, "--merge", "--delete-branch=false"]
            if not dry_run:
                subprocess.run(cmd, check=True, text=True)
            applied.append(
                {
                    "type": "merge_pr",
                    "issue": child["number"],
                    "pr": pr_number,
                    "dry_run": dry_run,
                }
            )
        elif action == "close_issue":
            cmd = ["gh", "issue", "close", str(child["number"]), "--repo", repo]
            if not dry_run:
                subprocess.run(cmd, check=True, text=True)
            applied.append(
                {
                    "type": "close_issue",
                    "issue": child["number"],
                    "dry_run": dry_run,
                }
            )
    return applied


def close_parent_issue_if_ready(plan: dict[str, Any], dry_run: bool) -> dict[str, Any] | None:
    if not plan["all_tracked_children_done"]:
        return None
    if plan["completion_blockers"]:
        return None
    if plan["parent"]["state"] == "CLOSED":
        return None

    owner_repo = plan["parent"]["repo"]
    parent_number = plan["parent"]["number"]
    cmd = ["gh", "issue", "close", str(parent_number), "--repo", owner_repo]
    if not dry_run:
        subprocess.run(cmd, check=True, text=True)
    return {
        "type": "close_parent_issue",
        "issue": parent_number,
        "dry_run": dry_run,
    }


def summarize_run_state(plan: dict[str, Any]) -> str:
    if plan["all_tracked_children_done"] and not plan["completion_blockers"]:
        return "done"
    if plan["ready_to_spawn"]:
        return "needs_spawn"
    if plan["follow_up_needed_issue_numbers"]:
        return "needs_follow_up"
    if plan["active_or_waiting_issue_numbers"]:
        return "waiting_for_children"
    return "blocked"


def reconcile_once(
    issue_ref: str,
    repo_override: str | None,
    ledger_path: Path,
    apply_followups: bool,
    close_parent_when_done: bool,
    dry_run: bool,
    write_ledger_enabled: bool,
) -> dict[str, Any]:
    plan = run_planner(issue_ref, repo_override, ledger_path)
    ledger = sync_ledger(planner.load_ledger(ledger_path), plan, issue_ref)
    applied_actions: list[dict[str, Any]] = []

    if apply_followups:
        applied_actions.extend(apply_github_followups(plan, plan["parent"]["repo"], dry_run))
        if applied_actions:
            plan = run_planner(issue_ref, repo_override, ledger_path)
            ledger = sync_ledger(ledger, plan, issue_ref)

    parent_close_action = None
    if close_parent_when_done:
        parent_close_action = close_parent_issue_if_ready(plan, dry_run)
        if parent_close_action:
            applied_actions.append(parent_close_action)

    if write_ledger_enabled:
        write_ledger(ledger_path, ledger)
    return {
        "status": summarize_run_state(plan),
        "ledger_path": str(ledger_path),
        "plan": plan,
        "applied_actions": applied_actions,
    }


def record_lane(
    issue_ref: str,
    repo_override: str | None,
    ledger_path: Path,
    child_number: int,
    agent_session: str | None,
    lease_state: str | None,
    branch: str | None,
    worktree: str | None,
    pr_number: int | None,
    checkpoint: str | None,
    next_expected_transition: str | None,
) -> dict[str, Any]:
    plan = run_planner(issue_ref, repo_override, ledger_path)
    ledger = sync_ledger(planner.load_ledger(ledger_path), plan, issue_ref)
    key = str(child_number)
    if key not in ledger["children"]:
        planner.fail(f"child issue #{child_number} is not in the tracked snapshot")

    entry = dict(ledger["children"][key])
    if agent_session is not None:
        entry["agent_session"] = agent_session
    if lease_state is not None:
        entry["lease_state"] = lease_state
    if branch is not None:
        entry["branch"] = branch
    if worktree is not None:
        entry["worktree"] = worktree
    if pr_number is not None:
        entry["pr"] = pr_number
    if checkpoint is not None:
        entry["current_checkpoint"] = checkpoint
        entry["last_heartbeat"] = utc_now()
    if next_expected_transition is not None:
        entry["next_expected_transition"] = next_expected_transition
    entry["updated_at"] = utc_now()
    ledger["children"][key] = entry
    ledger["updated_at"] = entry["updated_at"]
    write_ledger(ledger_path, ledger)
    return {
        "ledger_path": str(ledger_path),
        "child": entry,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Supervise a parent issue run using planner output plus a persisted run ledger."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(target: argparse.ArgumentParser) -> None:
        target.add_argument("issue", help="Issue URL, owner/repo#number, or #number")
        target.add_argument(
            "--repo",
            help="Repo override for bare issue numbers, for example kentoku24/comic_crawler",
        )
        target.add_argument(
            "--ledger",
            help="Optional run ledger path. Default: .codex/orchestrator-runs/issue-<parent>.json",
        )

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Refresh planner state, sync the ledger, and optionally apply GitHub follow-ups.",
    )
    add_common_arguments(reconcile_parser)
    reconcile_parser.add_argument(
        "--apply-followups",
        action="store_true",
        help="Merge approved PRs and close merged issues when the planner says it is safe.",
    )
    reconcile_parser.add_argument(
        "--close-parent-when-done",
        action="store_true",
        help="Close the parent issue once all tracked children are done and no blockers remain.",
    )
    reconcile_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not execute GitHub write actions. Ledger sync still runs.",
    )
    reconcile_parser.add_argument(
        "--no-write-ledger",
        action="store_true",
        help="Do not persist the reconciled ledger. Useful for diagnostic dry-runs.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Repeatedly reconcile until the run is done, blocked, or reaches the iteration limit.",
    )
    add_common_arguments(run_parser)
    run_parser.add_argument(
        "--apply-followups",
        action="store_true",
        help="Merge approved PRs and close merged issues when the planner says it is safe.",
    )
    run_parser.add_argument(
        "--close-parent-when-done",
        action="store_true",
        help="Close the parent issue once all tracked children are done and no blockers remain.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not execute GitHub write actions. Ledger sync still runs.",
    )
    run_parser.add_argument(
        "--no-write-ledger",
        action="store_true",
        help="Do not persist the reconciled ledger while polling.",
    )
    run_parser.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="Seconds to sleep between reconcile passes while children are active.",
    )
    run_parser.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        help="Maximum reconcile iterations before exiting.",
    )

    record_parser = subparsers.add_parser(
        "record-lane",
        help="Persist lane metadata such as agent session, worktree, branch, PR, and checkpoint.",
    )
    add_common_arguments(record_parser)
    record_parser.add_argument("child", type=int, help="Tracked child issue number")
    record_parser.add_argument("--agent-session", help="Spawned or resumed agent session id")
    record_parser.add_argument("--lease-state", help="Ledger lease state to persist")
    record_parser.add_argument("--branch", help="Lane branch name")
    record_parser.add_argument("--worktree", help="Lane worktree path")
    record_parser.add_argument("--pr-number", type=int, help="Open PR number")
    record_parser.add_argument("--checkpoint", help="Latest lane checkpoint")
    record_parser.add_argument("--next-expected-transition", help="Next expected checkpoint")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    ledger_path = default_ledger_path(args.issue, args.repo, args.ledger)

    if args.command == "reconcile":
        result = reconcile_once(
            args.issue,
            args.repo,
            ledger_path,
            args.apply_followups,
            args.close_parent_when_done,
            args.dry_run,
            not args.no_write_ledger,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "run":
        history: list[dict[str, Any]] = []
        final_result: dict[str, Any] | None = None
        for iteration in range(1, args.max_iterations + 1):
            result = reconcile_once(
                args.issue,
                args.repo,
                ledger_path,
                args.apply_followups,
                args.close_parent_when_done,
                args.dry_run,
                not args.no_write_ledger,
            )
            result["iteration"] = iteration
            history.append(
                {
                    "iteration": iteration,
                    "status": result["status"],
                    "ready_to_spawn": result["plan"]["ready_to_spawn"],
                    "active_or_waiting_issue_numbers": result["plan"]["active_or_waiting_issue_numbers"],
                    "follow_up_needed_issue_numbers": result["plan"]["follow_up_needed_issue_numbers"],
                    "completion_blockers": result["plan"]["completion_blockers"],
                    "applied_actions": result["applied_actions"],
                }
            )
            final_result = result

            if result["status"] in {"done", "needs_spawn", "needs_follow_up", "blocked"}:
                break

            time.sleep(args.poll_seconds)

        if final_result is None:
            planner.fail("supervisor did not run any iterations")

        print(
            json.dumps(
                {
                    "status": final_result["status"],
                    "ledger_path": final_result["ledger_path"],
                    "history": history,
                    "final_plan": final_result["plan"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "record-lane":
        result = record_lane(
            args.issue,
            args.repo,
            ledger_path,
            args.child,
            args.agent_session,
            args.lease_state,
            args.branch,
            args.worktree,
            args.pr_number,
            args.checkpoint,
            args.next_expected_transition,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    planner.fail(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
