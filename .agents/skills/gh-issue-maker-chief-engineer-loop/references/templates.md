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
- Branch (if parallel maker):
- Worktree (if parallel maker):
- Existing PR (if orchestrated-child):
- Requested terminal state (if orchestrated-child):
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

## Cycle Update

```text
Cycle Update
- Cycle:
- Goal:
- Execution mode:
- Terminal result: `done` | `reviewer_gate_pending` | `merge_pending` | `issue_close_pending` | `blocked` | `failed`
- Worktrees (if used):
  - ...
- Maker packets:
  - ...
- PR status:
- Evidence gained:
  - ...
- Chief Reviewer decision:
- Next move:
```
