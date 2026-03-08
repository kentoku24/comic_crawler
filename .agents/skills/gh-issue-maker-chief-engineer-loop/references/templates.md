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
- Existing Chief Engineer guidance:
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
- Requested terminal state (if orchestrated-child):
- Reporting checkpoints (if orchestrated-child):
  - `worktree_ready`
  - `pr_opened`
  - `review_state_changed`
  - `merged`
  - `issue_closed`
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

## Chief Reviewer Review Packet

```text
Chief Reviewer Review Packet
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

## Chief Reviewer Gate

```text
Chief Reviewer Gate
- Reviewer agent:
- Decision: APPROVE | NG
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
- Checkpoint: `worktree_ready` | `pr_opened` | `review_state_changed` | `merged` | `issue_closed`
- Terminal result: `in_progress` | `merge_pending` | `issue_close_pending` | `done` | `blocked` | `failed`
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
- Progress checkpoint: `planning` | `worktree_ready` | `pr_opened` | `review_state_changed` | `merged` | `issue_closed`
- Terminal result: `in_progress` | `done` | `reviewer_gate_pending` | `merge_pending` | `issue_close_pending` | `blocked` | `failed`
- Worktrees (if used):
  - ...
- Branches (if used):
  - ...
- Maker packets:
  - ...
- PR status:
- Evidence gained:
  - ...
- Chief Reviewer decision:
- Blockers:
  - ...
- Next move:
```
