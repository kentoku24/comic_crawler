#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, NoReturn


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
ISSUE_URL_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)$")
REPO_REF_RE = re.compile(r"^([^/\s]+)/([^#\s]+)#(\d+)$")
NUMBER_RE = re.compile(r"^#?(\d+)$")
ISSUE_REF_RE = re.compile(r"#(\d+)\b")
MERMAID_EDGE_RE = re.compile(r"I(\d+)(?:\[[^\]]*\])?\s*-->\s*I(\d+)")
TITLE_DEP_RE = re.compile(r"\(dep(?:endency|endencies)?\s*:\s*([^)]+)\)", re.IGNORECASE)

CHILD_SECTION_NAMES = [
    "子Issue",
    "Sub-issues",
    "Sub issues",
    "Child Issues",
]
DEPENDENCY_SECTION_NAMES = [
    "依存関係",
    "Dependencies",
]
ORDER_SECTION_NAMES = [
    "完了順の目安",
    "Suggested Order",
]
DOD_SECTION_NAMES = [
    "DoD",
]

ACTIVE_LEASE_STATES = {
    "spawned",
    "active",
    "waiting_child",
    "reviewer_gate_pending",
    "merge_pending",
    "issue_close_pending",
}
MERGE_BLOCKED_STATES = {
    "DIRTY",
    "BLOCKED",
    "BEHIND",
    "UNSTABLE",
    "HAS_HOOKS",
}


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def run_gh(args: list[str]) -> str:
    result = subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "gh command failed"
        fail(error)
    return result.stdout


def run_graphql(query: str, **variables: Any) -> dict[str, Any]:
    args = ["api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        args.extend(["-F", f"{name}={value}"])
    return json.loads(run_gh(args))


def normalize_issue_ref(raw: str, repo_override: str | None) -> tuple[str, str, int]:
    if match := ISSUE_URL_RE.match(raw):
        owner, repo, number = match.groups()
        return owner, repo, int(number)

    if match := REPO_REF_RE.match(raw):
        owner, repo, number = match.groups()
        return owner, repo, int(number)

    if match := NUMBER_RE.match(raw):
        if repo_override is None:
            repo_override = current_repo()
        if "/" not in repo_override:
            fail(f"invalid repo override: {repo_override}")
        owner, repo = repo_override.split("/", 1)
        return owner, repo, int(match.group(1))

    fail(f"unsupported issue reference: {raw}")


def current_repo() -> str:
    payload = json.loads(run_gh(["repo", "view", "--json", "nameWithOwner"]))
    return payload["nameWithOwner"]


def fetch_repo_default_branch(owner: str, repo: str) -> str:
    payload = json.loads(run_gh(["api", f"repos/{owner}/{repo}"]))
    return payload["default_branch"]


def fetch_issue_rest(owner: str, repo: str, number: int) -> dict[str, Any]:
    return json.loads(run_gh(["api", f"repos/{owner}/{repo}/issues/{number}"]))


def fetch_issue_graphql(owner: str, repo: str, number: int) -> dict[str, Any]:
    query = """
    query($owner:String!, $repo:String!, $number:Int!) {
      repository(owner:$owner, name:$repo) {
        issue(number:$number) {
          number
          state
          timelineItems(
            first:100
            itemTypes:[BLOCKED_BY_ADDED_EVENT, BLOCKING_ADDED_EVENT]
          ) {
            nodes {
              __typename
              ... on BlockedByAddedEvent {
                blockingIssue {
                  number
                  title
                  state
                  url
                }
              }
              ... on BlockingAddedEvent {
                blockedIssue {
                  number
                  title
                  state
                  url
                }
              }
            }
          }
          closedByPullRequestsReferences(first:20) {
            nodes {
              number
              title
              url
              state
              isDraft
              mergedAt
              reviewDecision
              mergeStateStatus
              headRefName
              baseRefName
            }
          }
        }
      }
    }
    """
    payload = run_graphql(query, owner=owner, repo=repo, number=number)
    issue = payload["data"]["repository"]["issue"]
    if issue is None:
        fail(f"issue #{number} was not found in {owner}/{repo}")
    return issue


def fetch_issue_context(owner: str, repo: str, number: int) -> dict[str, Any]:
    rest = fetch_issue_rest(owner, repo, number)
    graph = fetch_issue_graphql(owner, repo, number)

    blockers = []
    blocking = []
    for node in graph["timelineItems"]["nodes"]:
        typename = node["__typename"]
        if typename == "BlockedByAddedEvent":
            blockers.append(node["blockingIssue"])
        elif typename == "BlockingAddedEvent":
            blocking.append(node["blockedIssue"])

    return {
        "number": number,
        "title": rest["title"],
        "url": rest["html_url"],
        "state": rest["state"].upper(),
        "state_reason": (rest.get("state_reason") or "").upper(),
        "body": rest.get("body") or "",
        "comments": rest.get("comments") or 0,
        "closed_at": rest.get("closed_at"),
        "issue_dependencies_summary": rest.get("issue_dependencies_summary") or {},
        "blockers": blockers,
        "blocking": blocking,
        "closing_pull_requests": graph["closedByPullRequestsReferences"]["nodes"],
    }


def normalize_heading(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().lower())


def extract_section(body: str, candidates: list[str]) -> str | None:
    normalized_candidates = {normalize_heading(name) for name in candidates}
    lines = body.splitlines()
    captured: list[str] = []
    in_section = False
    section_level = 0

    for line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = normalize_heading(heading.group(2))
            if in_section and level <= section_level:
                break
            if not in_section and title in normalized_candidates:
                in_section = True
                section_level = level
                captured = []
                continue
        if in_section:
            captured.append(line)

    if not in_section:
        return None
    return "\n".join(captured).strip()


def extract_child_numbers(section: str) -> list[int]:
    numbers: list[int] = []
    seen: set[int] = set()
    for line in section.splitlines():
        match = re.match(r"^\s*-\s+#(\d+)\b", line)
        if not match:
            continue
        number = int(match.group(1))
        if number in seen:
            continue
        seen.add(number)
        numbers.append(number)
    return numbers


def extract_order_hint(section: str | None) -> dict[int, int]:
    if not section:
        return {}

    order_hint: dict[int, int] = {}
    for index, line in enumerate(section.splitlines()):
        match = re.match(r"^\s*\d+\.\s+#(\d+)\b", line)
        if match:
            order_hint[int(match.group(1))] = index
    return order_hint


def extract_mermaid_edges(section: str | None) -> list[tuple[int, int]]:
    if not section:
        return []

    edges: list[tuple[int, int]] = []
    in_mermaid = False

    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_mermaid and stripped == "```mermaid":
                in_mermaid = True
                continue
            if in_mermaid:
                in_mermaid = False
            continue
        if not in_mermaid:
            continue
        for match in MERMAID_EDGE_RE.finditer(line):
            edges.append((int(match.group(1)), int(match.group(2))))

    return edges


def extract_issue_refs(text: str) -> list[int]:
    return [int(value) for value in ISSUE_REF_RE.findall(text)]


def extract_child_metadata_edges(children: dict[int, dict[str, Any]]) -> list[tuple[int, int]]:
    edges: list[tuple[int, int]] = []
    for number, issue in children.items():
        if match := TITLE_DEP_RE.search(issue["title"]):
            for dependency in extract_issue_refs(match.group(1)):
                edges.append((dependency, number))

        section = extract_section(issue["body"], DEPENDENCY_SECTION_NAMES)
        if section:
            for dependency in extract_issue_refs(section):
                edges.append((dependency, number))

    return edges


def extract_list_items(section: str | None) -> list[str]:
    if not section:
        return []

    items: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if match := re.match(r"^-\s+(.*)$", stripped):
            items.append(match.group(1).strip())
            continue
        if match := re.match(r"^\d+\.\s+(.*)$", stripped):
            items.append(match.group(1).strip())
    return items


def dedupe_edges(edges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return list(dict.fromkeys(edges))


def build_prerequisites(
    child_numbers: list[int],
    raw_edges: list[tuple[int, int]],
) -> tuple[dict[int, set[int]], list[str], list[tuple[int, int]], list[tuple[int, int]]]:
    child_set = set(child_numbers)
    prerequisites = {number: set() for number in child_numbers}
    internal_edges: list[tuple[int, int]] = []
    external_edges: list[tuple[int, int]] = []
    warnings: list[str] = []

    for prerequisite, dependent in dedupe_edges(raw_edges):
        if prerequisite == dependent:
            warnings.append(f"ignored self dependency #{prerequisite}")
            continue
        if dependent not in child_set:
            warnings.append(
                f"ignored edge #{prerequisite} -> #{dependent} because #{dependent} is not in the tracked child snapshot"
            )
            continue
        if prerequisite in child_set:
            prerequisites[dependent].add(prerequisite)
            internal_edges.append((prerequisite, dependent))
        else:
            external_edges.append((prerequisite, dependent))

    return prerequisites, warnings, internal_edges, external_edges


def compute_waves(
    child_numbers: list[int],
    prerequisites: dict[int, set[int]],
    completed: set[int],
    order_hint: dict[int, int],
) -> list[list[int]]:
    pending = {number for number in child_numbers if number not in completed}
    remaining_prerequisites = {
        number: {value for value in prerequisites[number] if value in pending}
        for number in pending
    }
    waves: list[list[int]] = []

    while pending:
        ready = sorted(
            (number for number in pending if not remaining_prerequisites[number]),
            key=lambda number: (order_hint.get(number, len(order_hint)), number),
        )
        if not ready:
            blocked = {
                str(number): sorted(remaining_prerequisites[number])
                for number in sorted(pending)
            }
            fail(
                "cycle or unresolved dependency detected: "
                + json.dumps(blocked, ensure_ascii=False, sort_keys=True)
            )

        waves.append(ready)
        ready_set = set(ready)
        pending -= ready_set
        for dependencies in remaining_prerequisites.values():
            dependencies.difference_update(ready_set)

    return waves


def load_ledger(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}

    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"invalid run ledger at {path}: {exc}")


def has_active_lease(entry: dict[str, Any] | None) -> bool:
    if not entry:
        return False
    return (entry.get("lease_state") or "") in ACTIVE_LEASE_STATES


def sort_pull_requests(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(pr: dict[str, Any]) -> tuple[int, int, str]:
        if pr["state"] == "OPEN":
            rank = 0
        elif pr.get("mergedAt"):
            rank = 1
        else:
            rank = 2
        merged_at = pr.get("mergedAt") or ""
        return (rank, -pr["number"], merged_at)

    return sorted(prs, key=sort_key)


def choose_primary_open_pr(prs: list[dict[str, Any]]) -> dict[str, Any] | None:
    open_prs = [pr for pr in prs if pr["state"] == "OPEN"]
    if not open_prs:
        return None
    return sort_pull_requests(open_prs)[0]


def build_spawn_prompt(
    owner: str,
    repo: str,
    parent_number: int,
    child_number: int,
    default_branch: str,
    child_state: str,
    ledger_entry: dict[str, Any] | None,
    primary_pr: dict[str, Any] | None,
) -> str:
    lines = [
        "$gh-issue-maker-chief-engineer-loop を使ってこの Issue を進めてください。",
        f"https://github.com/{owner}/{repo}/issues/{child_number}",
        "",
        "Orchestrator context",
        f"- Parent issue: #{parent_number}",
        "- Execution mode: orchestrated-child",
        f"- Requested terminal state: merged closing PR on `{default_branch}` and issue closed",
        f"- Current orchestrator state: {child_state}",
    ]

    if primary_pr is not None:
        lines.append(f"- Existing closing PR: #{primary_pr['number']} {primary_pr['url']}")

    if ledger_entry:
        if branch := ledger_entry.get("branch"):
            lines.append(f"- Existing branch: {branch}")
        if worktree := ledger_entry.get("worktree"):
            lines.append(f"- Existing worktree: {worktree}")
        if run_id := ledger_entry.get("run_id"):
            lines.append(f"- Run id: {run_id}")

    lines.append(
        "- Do not return success at reviewer approval alone. If merge or issue close is still pending, return merge_pending or issue_close_pending."
    )
    return "\n".join(lines)


def classify_child(
    child: dict[str, Any],
    child_set: set[int],
    done_set: set[int],
    default_branch: str,
    ledger_entry: dict[str, Any] | None,
) -> tuple[str, list[int], list[int], dict[str, Any] | None, list[str], list[str], bool]:
    blockers = [issue["number"] for issue in child["blockers"]]
    internal_blockers = [number for number in blockers if number in child_set]
    external_blockers = [number for number in blockers if number not in child_set]
    unresolved_internal = [number for number in internal_blockers if number not in done_set]
    unresolved_external = external_blockers

    closing_prs = sort_pull_requests(child["closing_pull_requests"])
    merged_to_default = [
        pr for pr in closing_prs if pr.get("mergedAt") and pr["baseRefName"] == default_branch
    ]
    merged_off_default = [
        pr for pr in closing_prs if pr.get("mergedAt") and pr["baseRefName"] != default_branch
    ]
    primary_open_pr = choose_primary_open_pr(closing_prs)
    warnings: list[str] = []
    delivery_evidence = bool(merged_to_default)

    if child["state"] == "CLOSED" and not delivery_evidence:
        warnings.append(
            f"#{child['number']} is closed without a merged closing PR on `{default_branch}`"
        )

    if len([pr for pr in closing_prs if pr["state"] == "OPEN"]) > 1:
        warnings.append(f"#{child['number']} has multiple open closing PRs")

    if child["state"] == "CLOSED" and delivery_evidence:
        return (
            "done",
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            warnings,
            [pr["url"] for pr in merged_to_default],
            False,
        )

    if child["state"] == "CLOSED":
        return (
            "closed_without_delivery_evidence",
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            warnings,
            [],
            False,
        )

    if unresolved_internal:
        return (
            "blocked_by_dependencies",
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            warnings,
            [],
            False,
        )

    if unresolved_external:
        return (
            "blocked_by_external_dependency",
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            warnings,
            [],
            False,
        )

    if merged_to_default:
        return (
            "merged_pending_issue_close",
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            warnings,
            [pr["url"] for pr in merged_to_default],
            False,
        )

    if merged_off_default:
        warnings.append(
            f"#{child['number']} has a merged closing PR that did not target `{default_branch}`"
        )
        return (
            "merged_off_default_branch",
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            warnings,
            [pr["url"] for pr in merged_off_default],
            False,
        )

    if primary_open_pr is not None:
        review_decision = primary_open_pr.get("reviewDecision")
        merge_state = primary_open_pr.get("mergeStateStatus") or "UNKNOWN"

        if primary_open_pr["isDraft"]:
            state = "pr_draft"
        elif review_decision == "CHANGES_REQUESTED":
            state = "pr_changes_requested"
        elif review_decision == "APPROVED" and merge_state == "CLEAN":
            state = "pr_approved_pending_merge"
        elif review_decision == "APPROVED" and merge_state != "CLEAN":
            state = "pr_merge_blocked"
        elif merge_state in MERGE_BLOCKED_STATES:
            state = "pr_merge_blocked"
        else:
            state = "pr_review_pending"

        return (
            state,
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            warnings,
            [],
            False,
        )

    if has_active_lease(ledger_entry):
        return (
            "agent_active",
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            warnings,
            [],
            False,
        )

    return (
        "ready",
        unresolved_internal,
        unresolved_external,
        primary_open_pr,
        warnings,
        [],
        True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a parent issue into a tracked child snapshot, GitHub dependency graph, "
            "and orchestration states."
        )
    )
    parser.add_argument("issue", help="Issue URL, owner/repo#number, or #number")
    parser.add_argument(
        "--repo",
        help="Repo override for bare issue numbers, for example kentoku24/comic_crawler",
    )
    parser.add_argument(
        "--ledger",
        help="Optional run ledger path. Default: .codex/orchestrator-runs/issue-<parent>.json",
    )
    args = parser.parse_args()

    owner, repo, issue_number = normalize_issue_ref(args.issue, args.repo)
    default_branch = fetch_repo_default_branch(owner, repo)
    parent = fetch_issue_context(owner, repo, issue_number)
    parent_body = parent["body"]

    child_section = extract_section(parent_body, CHILD_SECTION_NAMES)
    if child_section is None:
        fail("could not find a child issue section in the parent issue body")

    current_child_numbers = extract_child_numbers(child_section)
    if not current_child_numbers:
        fail("could not find any child issue bullets in the parent issue body")

    ledger_path = (
        Path(args.ledger)
        if args.ledger
        else Path(".codex") / "orchestrator-runs" / f"issue-{issue_number}.json"
    )
    ledger = load_ledger(ledger_path)

    tracked_child_numbers = ledger.get("tracked_child_numbers") or current_child_numbers
    if sorted(tracked_child_numbers) != sorted(current_child_numbers):
        fail(
            "tracked child snapshot drift detected: "
            + json.dumps(
                {
                    "ledger": sorted(tracked_child_numbers),
                    "current_parent_issue_body": sorted(current_child_numbers),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    order_hint = extract_order_hint(extract_section(parent_body, ORDER_SECTION_NAMES))

    with ThreadPoolExecutor() as pool:
        fetched = pool.map(
            lambda number: (number, fetch_issue_context(owner, repo, number)),
            tracked_child_numbers,
        )
        children = dict(fetched)

    github_edges = []
    warnings: list[str] = []
    for number in tracked_child_numbers:
        child = children[number]
        blocker_numbers = [issue["number"] for issue in child["blockers"]]
        github_edges.extend((blocker, number) for blocker in blocker_numbers)

        summary = child["issue_dependencies_summary"]
        total_blocked_by = summary.get("total_blocked_by")
        if total_blocked_by is not None and total_blocked_by != len(blocker_numbers):
            warnings.append(
                f"GitHub dependency count mismatch on #{number}: "
                f"summary total_blocked_by={total_blocked_by}, "
                f"timeline blocker events={len(blocker_numbers)}"
            )

    parent_body_edges = extract_mermaid_edges(extract_section(parent_body, DEPENDENCY_SECTION_NAMES))
    child_metadata_edges = extract_child_metadata_edges(children)

    if github_edges:
        dependency_source = "github_dependency_events"
        raw_edges = github_edges
    elif parent_body_edges:
        dependency_source = "parent_mermaid_fallback"
        raw_edges = parent_body_edges
        warnings.append("falling back to parent mermaid dependencies because GitHub dependency events were empty")
    elif child_metadata_edges:
        dependency_source = "child_issue_metadata_fallback"
        raw_edges = child_metadata_edges
        warnings.append("falling back to child issue metadata because GitHub dependency events were empty")
    else:
        dependency_source = "none"
        raw_edges = []

    prerequisites, prerequisite_warnings, internal_edges, external_edges = build_prerequisites(
        tracked_child_numbers,
        raw_edges,
    )
    warnings.extend(prerequisite_warnings)

    if dependency_source == "none":
        warnings.append("no dependency edges found in GitHub, parent issue mermaid, or child issue metadata")

    tracked_child_set = set(tracked_child_numbers)
    body_edge_set = {
        edge
        for edge in dedupe_edges(parent_body_edges)
        if edge[0] in tracked_child_set and edge[1] in tracked_child_set
    }
    github_edge_set = set(dedupe_edges(github_edges))
    if github_edge_set and body_edge_set and github_edge_set != body_edge_set:
        warnings.append(
            "GitHub dependency events and parent issue mermaid differ: "
            + json.dumps(
                {
                    "github_only": sorted(github_edge_set - body_edge_set),
                    "parent_body_only": sorted(body_edge_set - github_edge_set),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    done_set = {
        number
        for number in tracked_child_numbers
        if children[number]["state"] == "CLOSED"
        and any(
            pr.get("mergedAt") and pr["baseRefName"] == default_branch
            for pr in children[number]["closing_pull_requests"]
        )
    }

    all_waves = compute_waves(tracked_child_numbers, prerequisites, set(), order_hint)
    remaining_waves = compute_waves(tracked_child_numbers, prerequisites, done_set, order_hint)

    child_records = []
    state_groups: dict[str, list[int]] = {}
    ready_to_spawn: list[int] = []
    active_or_waiting: list[int] = []
    follow_up_needed: list[int] = []

    for number in tracked_child_numbers:
        child = children[number]
        ledger_entry = (ledger.get("children") or {}).get(str(number))
        dod_items = extract_list_items(extract_section(child["body"], DOD_SECTION_NAMES))

        (
            orchestration_state,
            unresolved_internal,
            unresolved_external,
            primary_open_pr,
            child_warnings,
            delivery_evidence_urls,
            ready_now,
        ) = classify_child(
            child,
            set(tracked_child_numbers),
            done_set,
            default_branch,
            ledger_entry,
        )

        if ready_now:
            ready_to_spawn.append(number)
        if orchestration_state in {
            "agent_active",
            "pr_draft",
            "pr_review_pending",
            "pr_changes_requested",
            "pr_approved_pending_merge",
            "pr_merge_blocked",
            "merged_pending_issue_close",
            "merged_off_default_branch",
        }:
            active_or_waiting.append(number)
        if orchestration_state in {
            "pr_changes_requested",
            "pr_approved_pending_merge",
            "pr_merge_blocked",
            "merged_pending_issue_close",
            "closed_without_delivery_evidence",
            "merged_off_default_branch",
        }:
            follow_up_needed.append(number)

        state_groups.setdefault(orchestration_state, []).append(number)

        child_record = {
            "number": number,
            "title": child["title"],
            "url": child["url"],
            "issue_state": child["state"],
            "issue_state_reason": child["state_reason"],
            "blocked_by": sorted(prerequisites[number]),
            "blocked_by_external": sorted(
                prerequisite for prerequisite, dependent in external_edges if dependent == number
            ),
            "unresolved_blocked_by": sorted(unresolved_internal),
            "unresolved_external_blocked_by": sorted(unresolved_external),
            "blocking": sorted(issue["number"] for issue in child["blocking"]),
            "has_dod_section": bool(dod_items),
            "dod_items": dod_items,
            "closing_pull_requests": sort_pull_requests(child["closing_pull_requests"]),
            "primary_open_pr": primary_open_pr,
            "ledger": ledger_entry or {},
            "has_active_lease": has_active_lease(ledger_entry),
            "orchestration_state": orchestration_state,
            "delivery_evidence_urls": delivery_evidence_urls,
            "ready_to_spawn": ready_now,
        }
        if ready_now:
            child_record["spawn_prompt"] = build_spawn_prompt(
                owner,
                repo,
                issue_number,
                number,
                default_branch,
                orchestration_state,
                ledger_entry,
                primary_open_pr,
            )
        if child_warnings:
            child_record["warnings"] = child_warnings
            warnings.extend(child_warnings)
        child_records.append(child_record)

    result = {
        "parent": {
            "number": parent["number"],
            "title": parent["title"],
            "url": parent["url"],
            "state": parent["state"],
            "repo": f"{owner}/{repo}",
            "default_branch": default_branch,
        },
        "tracked_child_numbers": tracked_child_numbers,
        "ledger_path": str(ledger_path),
        "ledger_present": bool(ledger),
        "dependency_source": dependency_source,
        "dependency_edges": [
            {"from": prerequisite, "to": dependent}
            for prerequisite, dependent in sorted(internal_edges)
        ],
        "external_dependency_edges": [
            {"from": prerequisite, "to": dependent}
            for prerequisite, dependent in sorted(external_edges)
        ],
        "order_hint": [
            number for number, _ in sorted(order_hint.items(), key=lambda item: item[1])
        ],
        "done_issue_numbers": sorted(done_set),
        "ready_to_spawn": sorted(ready_to_spawn),
        "active_or_waiting_issue_numbers": sorted(active_or_waiting),
        "follow_up_needed_issue_numbers": sorted(follow_up_needed),
        "remaining_waves": remaining_waves,
        "all_waves": all_waves,
        "state_groups": {
            state: sorted(numbers) for state, numbers in sorted(state_groups.items())
        },
        "all_tracked_children_done": len(done_set) == len(tracked_child_numbers),
        "children": child_records,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
