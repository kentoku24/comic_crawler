#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import NoReturn


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


def fetch_issue(owner: str, repo: str, number: int) -> dict:
    payload = run_gh(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "number,title,body,url,state",
        ]
    )
    return json.loads(payload)


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


def extract_child_metadata_edges(children: dict[int, dict]) -> list[tuple[int, int]]:
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


def dedupe_edges(edges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return list(dict.fromkeys(edges))


def build_prerequisites(
    child_numbers: list[int],
    parent_number: int,
    raw_edges: list[tuple[int, int]],
) -> tuple[dict[int, set[int]], list[str], list[tuple[int, int]]]:
    child_set = set(child_numbers)
    prerequisites = {number: set() for number in child_numbers}
    warnings: list[str] = []
    cleaned_edges: list[tuple[int, int]] = []

    for prerequisite, dependent in dedupe_edges(raw_edges):
        if dependent == parent_number:
            continue
        if prerequisite == dependent:
            warnings.append(f"ignored self dependency #{prerequisite}")
            continue
        if prerequisite not in child_set or dependent not in child_set:
            warnings.append(
                f"ignored edge #{prerequisite} -> #{dependent} because it does not connect two child issues"
            )
            continue
        prerequisites[dependent].add(prerequisite)
        cleaned_edges.append((prerequisite, dependent))

    return prerequisites, warnings, cleaned_edges


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


def build_spawn_prompt(owner: str, repo: str, number: int) -> str:
    return (
        "$gh-issue-maker-chief-engineer-loop を使ってこの Issue を進めてください。\n"
        f"https://github.com/{owner}/{repo}/issues/{number}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve child issue dependency waves from a parent GitHub issue."
    )
    parser.add_argument("issue", help="Issue URL, owner/repo#number, or #number")
    parser.add_argument(
        "--repo",
        help="Repo override for bare issue numbers, for example kentoku24/comic_crawler",
    )
    args = parser.parse_args()

    owner, repo, issue_number = normalize_issue_ref(args.issue, args.repo)
    parent = fetch_issue(owner, repo, issue_number)

    body = parent.get("body") or ""

    child_section = extract_section(body, CHILD_SECTION_NAMES)
    if child_section is None:
        fail("could not find a child issue section in the parent issue body")

    child_numbers = extract_child_numbers(child_section)
    if not child_numbers:
        fail("could not find any child issue bullets in the parent issue body")

    order_hint = extract_order_hint(extract_section(body, ORDER_SECTION_NAMES))
    with ThreadPoolExecutor() as pool:
        fetched = pool.map(lambda n: (n, fetch_issue(owner, repo, n)), child_numbers)
        children = dict(fetched)

    raw_edges = extract_mermaid_edges(
        extract_section(body, DEPENDENCY_SECTION_NAMES)
    )
    dependency_source = "parent_mermaid"
    if not raw_edges:
        raw_edges = extract_child_metadata_edges(children)
        dependency_source = "child_issue_metadata" if raw_edges else "none"

    prerequisites, warnings, dependency_edges = build_prerequisites(
        child_numbers, parent["number"], raw_edges
    )
    if dependency_source == "none":
        warnings.append("no dependency edges found in the parent issue or child issues")

    closed = {
        number for number, issue in children.items() if issue["state"] == "CLOSED"
    }
    all_waves = compute_waves(child_numbers, prerequisites, set(), order_hint)
    remaining_waves = compute_waves(child_numbers, prerequisites, closed, order_hint)
    ready_now = set(remaining_waves[0]) if remaining_waves else set()

    child_records = []
    for number in child_numbers:
        issue = children[number]
        child_records.append(
            {
                "number": number,
                "title": issue["title"],
                "url": issue["url"],
                "state": issue["state"],
                "blocked_by": sorted(prerequisites[number]),
                "ready_now": number in ready_now,
                "spawn_prompt": build_spawn_prompt(owner, repo, number),
            }
        )

    result = {
        "parent": {
            "number": parent["number"],
            "title": parent["title"],
            "url": parent["url"],
            "state": parent["state"],
            "repo": f"{owner}/{repo}",
        },
        "dependency_source": dependency_source,
        "order_hint": [
            number for number, _ in sorted(order_hint.items(), key=lambda item: item[1])
        ],
        "dependency_edges": [
            {"from": prerequisite, "to": dependent}
            for prerequisite, dependent in dependency_edges
        ],
        "closed_issue_numbers": sorted(closed),
        "remaining_waves": remaining_waves,
        "all_waves": all_waves,
        "children": child_records,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
