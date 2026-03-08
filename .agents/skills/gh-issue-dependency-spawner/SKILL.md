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

この skill において `spawn` は開始イベントであり、完了ではない。
親セッションは lane を作って終わりではなく、各 child issue を `spawn -> heartbeat -> PR open -> review -> merge -> issue close` の checkpoint で追跡し、GitHub state で completion を確定する。

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
- spawn 後の heartbeat を確認し、worktree / branch / PR の lane identity を ledger に確定する
- stale lane や malformed lane を検知し、resume / replace / manual follow-up を判断する
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
- `children.<issue>.last_heartbeat`
- `children.<issue>.last_github_reconcile_at`
- `children.<issue>.next_expected_transition`
- `children.<issue>.updated_at`

同じ child issue に active lease が残っている間は、同じ issue を再 spawn してはならない。
再開時は `spawn` ではなく `resume` を優先する。

ledger は「spawn したことの記録」ではなく「今その lane がどこまで進んだか」の記録である。
agent id だけでなく、最後に確認できた worktree / branch / PR / checkpoint を残し、GitHub 実状態とのずれを検知できるようにする。

## Core Workflow

### 1. Parent issue を orchestration snapshot に変換する

まず supervisor を実行する。

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_supervisor.py reconcile <issue>
```

diagnostic だけ欲しいときは planner を直接実行してよい。

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_plan.py <issue>
```

supervisor / planner は次を返す。

- tracked child issues
- GitHub dependency edges
- child state machine の現在値
- `ready_to_spawn`
- `active_or_waiting`
- `done`
- merge / close follow-up が必要な child issues
- parent が次に取る action groups
- completion blockers
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

spawn した瞬間に lane を「進行中」とはみなさない。
親セッションは spawn 直後に ledger へ仮 lease を記録し、最初の heartbeat で branch / worktree / session を確定させる。
spawn / resume の直後に `issue_dependency_supervisor.py record-lane ...` を呼び、agent session と lane identity を ledger に残す。

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
- reporting checkpoints
- stop conditions

`$gh-issue-maker-chief-engineer-loop` が reviewer approve で止まるままなら、parent はその child を `done` と扱ってはならない。
child packet では、少なくとも `worktree_ready`, `pr_opened`, `review_state_changed`, `merged`, `issue_closed` の checkpoint を heartbeat で返すよう要求する。

### 4. Reconcile loop を回す

child agent が一度応答したら終わりではない。
親セッションは lane ごとに、checkpoint 遷移のたびに GitHub state を再取得して次を判断する。

- PR はできたか
- PR は draft か
- review decision は何か
- merge されたか
- issue は閉じたか
- blocker issue は `done` になったか

この reconcile を経ずに downstream を開けてはならない。

checkpoint は少なくとも次を持つ。

- `spawned`: agent は起動したが lane identity 未確定
- `worktree_ready`: branch / worktree / session が確定した
- `pr_opened`: open PR ができた
- `review_state_changed`: review state が変わった
- `merged`: closing PR が default branch に merge された
- `issue_closed`: issue close を確認した

どの checkpoint にも進まない lane は放置せず、parent が `resume`, `replace`, `manual_follow_up` のどれかに落とし込む。

### 5. Lane health を管理する

親セッションは active lease を「生きているから安全」とはみなさない。
少なくとも次を見て stale / malformed lane を検知する。

- active lease があるのに branch / worktree heartbeat が来ない
- worktree はあるのに PR がいつまでも現れない
- PR はあるのに review / merge 状態の更新が追えない
- child agent が `success` と言うが GitHub では open PR / open issue のまま
- branch / worktree / PR の組み合わせが ledger と GitHub で矛盾する

stale / malformed lane を見つけたら、親セッションは次の優先順で介入する。

1. 同じ session の `resume`
2. 同じ branch / worktree を引き継いだ `replace`
3. GitHub metadata だけで安全に解消できる follow-up

### 6. Merge / close follow-up を処理する

child issue が reviewer approve に到達しても、merge されていなければ `done` ではない。
次のどちらかを行う。

- child を resume して merge / close まで進めさせる
- parent が安全に GitHub metadata 操作だけ補助する

親セッションは merge 済みで issue が open のままなら `merged_pending_issue_close` として扱い、close まで追う。

PR open や reviewer approve は「進捗」であり、終了条件ではない。
親セッションは最後に GitHub で merge と issue close を確認するまで run を閉じてはならない。

### 7. Autonomous parent run loop を回す

この skill を使う親セッションは、`spawn` や進捗共有のたびに `final` を返してはならない。
run は次の loop を、completion か fatal stop condition まで繰り返す。

1. supervisor を実行して snapshot と action groups を再取得する
2. `spawn`, `resume_rework`, `merge_pr`, `close_issue`, `manual_audit` の必要がある child を処理する
3. active lane がある間は `wait` を使って child agent の heartbeat / 完了を待つ
4. `wait` から戻ったら GitHub state を再取得して reconcile する
5. `all_tracked_children_done=true` になるまで 1 に戻る

親セッションは commentary で進捗を返してよいが、それは中間報告である。
user に「進捗どお？」と聞かれるまで止まるのではなく、skill 自身が loop を持つ。

通常運転では planner を直接 orchestration source of truth にしてはならない。
親セッションは `issue_dependency_supervisor.py` を control plane として使い、planner は診断や diff 確認に限定する。

親の標準実行手順は次で固定する。

1. `issue_dependency_supervisor.py reconcile <issue>` を実行して `action_groups` と `completion_blockers` を得る
2. `spawn` 対象ごとに child の `spawn_prompt` を使って `spawn_agent` または `resume` を行う
3. spawn / resume の直後に `issue_dependency_supervisor.py record-lane ...` で `agent_session`, `branch`, `worktree`, `checkpoint` を ledger に記録する
4. active lane がある間は `wait` で child heartbeat / completion を待つ
5. heartbeat や lane identity が増えたら `record-lane` で ledger を更新する
6. `issue_dependency_supervisor.py reconcile <issue> --apply-followups --close-parent-when-done` を再実行する
7. `completion_blockers=[]` かつ parent issue close 判定まで済むまで 1 に戻る

この 1-7 を踏まずに、spawn 後の主観や child agent の自己申告だけで進めてはならない。

### 8. Completion を判定する

この skill が終了してよいのは、tracked set の全 child issue が `done` になったときだけである。

次の状態では終了してはならない。

- open issue が 1 件でもある
- merged されていない closing PR がある
- closed だが delivery evidence のない issue がある
- snapshot drift が unresolved
- ledger に active lease が残っている
- spawn 後に checkpoint が確定していない lane がある

親セッションは少なくとも次のどれかが真の間は `final` を返してはならない。

- `ready_to_spawn` が空でない
- `active_or_waiting_issue_numbers` が空でない
- `follow_up_needed_issue_numbers` が空でない
- `completion_blockers` が空でない
- parent issue close がまだ未実施で、close 可否の最終確認が終わっていない

## Commands

### Orchestration snapshot を出す

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_plan.py https://github.com/kentoku24/comic_crawler/issues/6
```

### Supervisor を 1 pass 回す

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_supervisor.py reconcile https://github.com/kentoku24/comic_crawler/issues/6 --apply-followups
```

ledger を汚さない診断だけ欲しいときは `--dry-run --no-write-ledger` を付ける。

### Supervisor を polling 付きで回す

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_supervisor.py run https://github.com/kentoku24/comic_crawler/issues/6 --apply-followups --poll-seconds 30 --max-iterations 20
```

### Spawn / resume した lane を ledger に記録する

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_supervisor.py record-lane https://github.com/kentoku24/comic_crawler/issues/6 41 --agent-session 019ccbc1-0763-7c62-8bf5-55157c397970 --lease-state active --branch codex/issue-41-outbox-replay --worktree /tmp/comic_crawler-issue-41-outbox-replay --checkpoint worktree_ready
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
- spawn acknowledgement や初回 heartbeat を completion と誤認しない
- PR が open になっただけで lane を成功扱いしない
- merge / issue close は GitHub で再取得してから報告する
- 「中間進捗を返したので仕事は継続中」という暗黙運用に依存しない
- active lane が残っているのに親 turn を閉じない
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
- checkpoint が進んだ child issue
- 新しく ready になった child issue
- merge / close が必要な child issue
- stale / malformed lane と、その介入方針
- 親が次に取る action groups (`spawn`, `monitor_pr`, `merge_pr`, `close_issue`, `manual_audit`)
- `completion_blockers`
- fatal drift / dependency mismatch の有無

最後は次をまとめる。

- `done` child issues
- `not-done` child issues
- parent issue を閉じてよいか
- 次回 run が必要なら、その理由
