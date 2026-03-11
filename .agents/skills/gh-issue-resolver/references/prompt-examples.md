# Prompt Examples

必要なときだけこのファイルを読む。
この skill は workflow を内包しているので、最小入力は Issue 指定だけで十分。

## 1. 取りうる入力

### 必須

- `Issue`: `<owner/repo#number>` または Issue URL

### 任意

- `Existing PR`: 既存 PR を引き継ぐとき
- `Existing branch / worktree`: 既存 branch や worktree を再利用するとき
- `merge:false | <branch>`: merger step で self-merge と merge target を指定するとき

### orchestrated-child のときだけ使う入力

- `Execution mode: orchestrated-child`
- `Parent issue`
- `Run id`
- `Requested terminal state`
- `Reporting checkpoints`

`merge:<branch>` は merger step まで進んだときだけ意味を持つ。指定された `<branch>` は PR base と self-merge target を兼ねる。指定がなければ merge は実行しない。`merge:true` は legacy 表現として扱い、新しい prompt では使わない。

## 2. 基本形

```text
Use $gh-issue-resolver on this issue:
<owner/repo#number or issue URL>
```

## 3. 日本語の基本形

```text
$gh-issue-resolver を使ってこの Issue を進めてください。

対象 Issue:
<owner/repo#number or issue URL>
```

## 4. 任意引数を足す形

```text
$gh-issue-resolver を使ってこの Issue を進めてください。

対象 Issue:
<owner/repo#number or issue URL>

Existing PR:
<PR URL or owner/repo#number>

Existing branch / worktree:
<branch name>, <worktree path>

merge:main
```

## 5. orchestrated-child で渡す形

```text
Use $gh-issue-resolver on this issue:
<owner/repo#number or issue URL>

Execution mode: orchestrated-child
Parent issue: <owner/repo#number or issue URL>
Run id: <run id>
Existing PR: <PR URL or owner/repo#number>
Existing branch / worktree: <branch name>, <worktree path>
Requested terminal state: ready_to_merge | merged | done
Reporting checkpoints: worktree_ready, pr_opened, review_state_changed, merger_state_changed
merge:codex/orch/83
```
