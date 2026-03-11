# Prompt Examples

## Basic Invocation

```text
$issue-graph-orchestrator https://github.com/org/repo/issues/83
```

この 1 行だけでよい。integration branch は parent issue の番号と title から自動生成する。

例として parent issue #83 の title が `Issue Graph Orchestrator` なら、
integration branch は `codex/orch/83-issue-graph-orchestrator` になる。

## Child Lane Shape

```text
Use $gh-issue-resolver on this issue:
org/repo#90

Execution mode: orchestrated-child
Parent issue: org/repo#83
Run id: orch-83-lane-90
Requested terminal state: merged
Reporting checkpoints: worktree_ready, pr_opened, review_state_changed, merger_state_changed
merge:<integration-branch>
```
