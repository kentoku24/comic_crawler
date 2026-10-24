# Issue Loop Templates

必要なときだけこのファイルを読む。
この skill で使う packet と gate report を最小限に揃えている。

## Issue Brief

```text
Issue Brief
- Issue:
- Problem:
- Desired outcome:
- Accepted scope:
  - ...
- Acceptance criteria:
  - ...
- Non-goals:
  - ...
- Existing gh-issue-reviewer guidance:
  - ...
- Constraints:
  - ...
- Open questions:
  - ...
```

## Capability Matrix

広い対象語を含む Issue では Issue Brief に追加する。

```text
Capability Matrix
- Target universe:
  - ...
- Explicit exclusions:
  - ...
- Per-target capability:
  - <target>:
      - included: yes | no
      - searchable / discoverable: yes | no | n/a
      - resolvable / executable: yes | no | partial
      - confidence / limitation:
      - fallback behavior:
- False-negative prevention:
  - ...
- Acceptance criteria linked to matrix:
  - ...
```

## Maker Packet

```text
Maker Packet
- Packet ID:
- Objective:
- Why this packet matters:
- Source issue:
- Execution mode: `spawn_agent` | `codex exec` | `/fork` | `degraded` | `orchestrated-child`
- Parent issue (if orchestrated-child):
- Run id (if orchestrated-child):
- Existing session / lease (if orchestrated-child):
- Branch (if parallel maker):
- Worktree (if parallel maker):
- Existing PR (if orchestrated-child):
- Merge target (optional): `<branch>`
- Requested terminal state (if orchestrated-child):
- Reporting checkpoints (if orchestrated-child):
  - `worktree_ready`
  - `pr_opened`
  - `review_state_changed`
  - `merger_state_changed`
- Relevant files:
  - ...
- Constraints:
  - ...
- Deliverable:
- Suggested checks:
  - ...
- Stop conditions:
  - ...
```

## PR Reviewer Review Packet

```text
PR Reviewer Review Packet
- Issue:
- PR:
- Cycle:
- Review execution mode: `spawn_agent` (independent context)
- Implemented packets:
  - ...
- Changed files:
  - ...
- Diff summary:
- Verification evidence:
  - ...
- Known gaps:
  - ...
- Requested decision: APPROVE | NG
```

## Review Thread Inventory

```text
Review Thread Inventory
- PR:
- Thread count:
- Threads:
  - URL:
    Reviewer claim:
    Verified conclusion:
    Code/test evidence:
    Resolved: yes | no
    Remaining action:
```

## Bounded Gate Packet

reviewer / merger agent が timeout し続ける場合だけ使う。成果物を gate comment と URL に絞る。

```text
Bounded Gate Packet
- Gate: gh-pr-reviewer | merger
- PR:
- Head:
- Issue:
- Changed files:
  - ...
- Scope summary:
  - ...
- Verification evidence:
  - ...
- Required checks:
  - ...
- Required comment:
  - literal signature: `$gh-pr-reviewer` | `$merger`
  - final line: APPROVE | NG
- Merge requested: true | false
- Return only:
  - Decision:
  - PR comment URL:
  - Blocker if NG:
```

## PR Reviewer Gate

```text
PR Reviewer Gate
- PR Reviewer agent:
- Decision: APPROVE | NG
- Blocking issues:
  - ...
- Required rework:
  - ...
- Residual risks:
  - ...
```

## Merger Packet

```text
Merger Packet
- Issue:
- PR:
- Merger execution mode: `spawn_agent` (independent context)
- PR Reviewer prerequisite:
- Merge target (optional): `<branch>`
- Verification evidence:
  - ...
- Known gaps:
  - ...
- Requested decision: APPROVE | NG
```

## Merger Gate

```text
Merger Gate
- Merger agent:
- Decision: APPROVE | NG
- Merge target:
- Merge executed: yes | no
- Blocking issues:
  - ...
- Required rework:
  - ...
- Residual risks:
  - ...
```

## Orchestrated Child Heartbeat

```text
Orchestrated Child Heartbeat
- Issue:
- Parent issue:
- Run id:
- Checkpoint: `worktree_ready` | `pr_opened` | `review_state_changed` | `merger_state_changed`
- Terminal result: `in_progress` | `gh-pr-reviewer-gate-pending` | `merger_pending` | `ready_to_merge` | `merged` | `done` | `blocked` | `failed`
- Branch:
- Worktree:
- PR:
- Blockers:
  - ...
- Evidence gained:
  - ...
- Next move:
```

## Cycle Update

```text
Cycle Update
- Cycle:
- Goal:
- Execution mode:
- Progress checkpoint: `planning` | `worktree_ready` | `pr_opened` | `review_state_changed` | `merger_state_changed`
- Terminal result: `in_progress` | `done` | `gh-pr-reviewer-gate-pending` | `merger_pending` | `ready_to_merge` | `merged` | `blocked` | `failed`
- Worktrees (if used):
  - ...
- Branches (if used):
  - ...
- Maker packets:
  - ...
- PR status:
- Evidence gained:
  - ...
- PR Reviewer decision:
- Merger decision:
- Blockers:
  - ...
- Next move:
```
