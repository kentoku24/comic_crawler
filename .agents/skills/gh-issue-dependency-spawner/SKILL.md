---
name: gh-issue-dependency-spawner
description: >
  comic_crawler の Epic / 管理 Issue を起点に、開始時点の child issue 群を
  1 つの tracked set として固定し、dependency order を守りながら各 child issue を
  `$gh-issue-maker-chief-engineer-loop` に委譲して、全 child issue の DoD が
  満たされるまで進める parent-issue orchestrator。親セッションは実装せず、
  GitHub state と run ledger を source of truth に spawn / resume / merge follow-up を
  管理する。Use when: #6 のように child issue と依存関係が整理された管理 Issue を、
  wave 単位の一回きり spawn ではなく、sub-issue 完了まで継続運転したいとき。
---

# GitHub Parent Issue Orchestrator

## Overview

この skill は `dependency wave spawner` ではなく、**1 つの parent issue にぶら下がる child issue 群の実行オーケストレーター**である。
開始時点の child issue 一覧を tracked set として固定し、その集合に含まれる issue がすべて terminal state `done` に到達するまで進める。

この skill の終了条件は明確に次である。

- 呼び出し開始時に tracked set として確定した child issue がすべて `done`
- parent issue 自身の DoD を child issue 完了状態と矛盾なく説明できる

ここで `done` は単なる `CLOSED` でも child agent の `success` でもない。少なくとも次を満たす。

- issue が GitHub 上で `CLOSED`
- その issue を closing する PR が default branch に merge 済み、または同等の delivery evidence がある
- child loop が `reviewer gate pending` / `merge pending` / `blocked` を残していない

## Parent Responsibilities

親セッションは worker ではなく orchestrator であり、次に責務を限定する。

- parent issue から tracked child snapshot を確定する
- GitHub dependency と linked PR state を読み、child issue の state machine を継続的に reconcile する
- run ledger を維持し、child ごとの branch / worktree / PR / session / lease を管理する
- ready な child issue だけを spawn または resume する
- reviewer approve 後の merge / issue close follow-up が必要なら、それを child へ戻すか parent が安全に補助する
- 全 child issue が `done` になるまで続ける

親セッションは次をしてはならない。

- 実装
- repo ファイル編集
- child issue の代わりにテストを作ること
- dependency graph が曖昧なまま推測で downstream を開けること

## Preconditions

次を満たすときだけこの skill を使う。

- 対象は comic_crawler の GitHub Issue である
- parent issue に child issue 一覧がある
- `$gh-issue-maker-chief-engineer-loop` が使える
- native な agent spawn / resume が使える
- parallel child を分離する worktree 運用が使える

次のどれかに当てはまる場合は止まる。

- tracked child issue を一意に特定できない
- GitHub dependency を安全に復元できない
- run ledger を作れない、または既存 ledger と GitHub state が矛盾している
- child loop を別 context で起動できない

## Source Of Truth

この skill が優先する source of truth は次の順序で固定する。

1. GitHub issue dependency events (`BlockedByAddedEvent` / `BlockingAddedEvent`)
2. GitHub issue / PR state (`OPEN` / `CLOSED`, merged PR, review state, merge state)
3. run ledger
4. parent issue body に書かれた child list と依存図

parent issue body の mermaid や順序リストは **宣言** としては有用だが、GitHub 実状態と矛盾したら GitHub を優先する。
ただし GitHub dependency event を取得できず、body 依存図とも整合しない場合は止まる。

## Tracked Child Snapshot

この skill は呼び出し開始時に child issue 一覧を snapshot として固定する。

- tracked set は start 時点の child issue 群
- run 中に新しい child issue が parent に追加されたら、その run は自動取り込みしない
- tracked set が途中で変わったら `snapshot drift` として止め、parent issue を再計画してから再実行する

「終了時に全部終わっているべき対象」は、**start 時点の tracked set** である。

## Child State Machine

各 child issue は少なくとも次の state を取る。

- `done`
- `blocked_by_dependencies`
- `blocked_by_external_dependency`
- `ready`
- `agent_active`
- `pr_draft`
- `pr_review_pending`
- `pr_changes_requested`
- `pr_approved_pending_merge`
- `pr_merge_blocked`
- `merged_pending_issue_close`
- `closed_without_delivery_evidence`
- `failed`

次のものは `done` ではない。

- issue が `OPEN`
- issue が `CLOSED` だが merged closing PR がない
- reviewer が `APPROVE` を返しただけで merge されていない
- child agent が `success` と言っただけで GitHub state が追随していない

## Run Ledger

親セッションは run ごとに ledger を持つ。
推奨パスは `.codex/orchestrator-runs/issue-<parent-number>.json` とする。

ledger には少なくとも次を持つ。

- `parent_issue`
- `run_id`
- `tracked_child_numbers`
- `dependency_edges`
- `children.<issue>.state`
- `children.<issue>.branch`
- `children.<issue>.worktree`
- `children.<issue>.pr`
- `children.<issue>.agent_session`
- `children.<issue>.lease_state`
- `children.<issue>.updated_at`

同じ child issue に active lease が残っている間は、同じ issue を再 spawn してはならない。
再開時は `spawn` ではなく `resume` を優先する。

## Core Workflow

### 1. Parent issue を orchestration snapshot に変換する

まず補助スクリプトを実行する。

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_plan.py <issue>
```

このスクリプトは次を返す。

- tracked child issues
- GitHub dependency edges
- child state machine の現在値
- `ready_to_spawn`
- `active_or_waiting`
- `done`
- merge / close follow-up が必要な child issues
- warnings / errors

`warnings` のうち dependency graph や snapshot integrity に関わるものは fatal とみなし、止まる。

### 2. Ready children を spawn または resume する

spawn 対象は `ready` な child issue だけである。
同じ wave の child issue でも、`agents.max_threads` と既存 active lease を超えて同時起動してはならない。

child issue ごとに次を決める。

- `spawn` するか
- 既存 session を `resume` するか
- merge / close follow-up だけ行うか

parallel child は必ず child issue ごとの専用 branch / worktree に分離する。

### 3. Child packet を渡す

child への packet は issue URL だけで終わらせてはならない。
少なくとも次を含める。

- source issue
- parent issue
- execution mode: `orchestrated-child`
- requested terminal state: `merged closing PR on default branch and issue closed`
- existing PR
- existing branch / worktree
- run id
- stop conditions

`$gh-issue-maker-chief-engineer-loop` が reviewer approve で止まるままなら、parent はその child を `done` と扱ってはならない。

### 4. Reconcile する

child agent が一度応答したら終わりではない。
親セッションは GitHub state を再取得して次を判断する。

- PR はできたか
- PR は draft か
- review decision は何か
- merge されたか
- issue は閉じたか
- blocker issue は `done` になったか

この reconcile を経ずに downstream を開けてはならない。

### 5. Merge / close follow-up を処理する

child issue が reviewer approve に到達しても、merge されていなければ `done` ではない。
次のどちらかを行う。

- child を resume して merge / close まで進めさせる
- parent が安全に GitHub metadata 操作だけ補助する

親セッションは merge 済みで issue が open のままなら `merged_pending_issue_close` として扱い、close まで追う。

### 6. Completion を判定する

この skill が終了してよいのは、tracked set の全 child issue が `done` になったときだけである。

次の状態では終了してはならない。

- open issue が 1 件でもある
- merged されていない closing PR がある
- closed だが delivery evidence のない issue がある
- snapshot drift が unresolved
- ledger に active lease が残っている

## Commands

### Orchestration snapshot を出す

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_plan.py https://github.com/kentoku24/comic_crawler/issues/6
```

### Parent issue を読む

```bash
gh api repos/kentoku24/comic_crawler/issues/6
```

### Child issue dependency events を読む

```bash
gh api graphql -f query='query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){issue(number:$number){timelineItems(first:100,itemTypes:[BLOCKED_BY_ADDED_EVENT,BLOCKING_ADDED_EVENT]){nodes{__typename ... on BlockedByAddedEvent { blockingIssue { number } } ... on BlockingAddedEvent { blockedIssue { number } }}}}}}' -F owner=kentoku24 -F repo=comic_crawler -F number=21
```

## Guardrails

- `CLOSED` だけで child issue を `done` 扱いしない
- reviewer approve だけで downstream を開けない
- child agent の `success` を GitHub state より優先しない
- active lease のある child issue を二重 spawn しない
- tracked set の途中変更を黙って飲み込まない
- dependency source of truth が unsafe なときに推測で進めない
- parent は code worker ではない。実装は child issue に委譲する
- 同時並行の child issue は worktree を共有しない

## Output Expectations

最初に次を短く共有する。

- parent issue
- tracked child snapshot
- done issues
- ready issues
- active / waiting issues
- blocked issues
- follow-up needed issues

各 reconcile 後は次を共有する。

- state change した child issue
- 新しく ready になった child issue
- merge / close が必要な child issue
- fatal drift / dependency mismatch の有無

最後は次をまとめる。

- `done` child issues
- `not-done` child issues
- parent issue を閉じてよいか
- 次回 run が必要なら、その理由
