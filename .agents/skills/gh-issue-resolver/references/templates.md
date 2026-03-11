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
- Merge target: `false` | `<branch>`
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
- Merge target: `false` | `<branch>`
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
