# Prompt Examples

## Basic Invocation

```text
$issue-graph-orchestrator https://github.com/org/repo/issues/83
```

この呼び出しでは次を暗黙に採用する。

- integration branch: `codex/orch/83`
- child lane invocation: `/gh-issue-resolver <child> merge:codex/orch/83`
- parent PR merge: disabled

## Expanded Invocation

```text
Use $issue-graph-orchestrator on this parent issue:
https://github.com/org/repo/issues/83
```

## Child Lane Shape

```text
Use $gh-issue-resolver on this issue:
org/repo#90

Execution mode: orchestrated-child
Parent issue: org/repo#83
Run id: orch-83-lane-90
Requested terminal state: merged
Reporting checkpoints: worktree_ready, pr_opened, review_state_changed, merger_state_changed
merge:codex/orch/83
```
