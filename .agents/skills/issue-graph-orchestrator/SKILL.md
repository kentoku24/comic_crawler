---
name: issue-graph-orchestrator
description: >
  親 Issue に明示された child issue と dependency graph を読み取り、
  integration branch を自動作成した上で、ready な child issue を
  `gh-issue-resolver` に `merge:<integration-branch>` を付けて並列実行する
  orchestrator。Use when: 親 Issue 1 つを起点に child issue 群を依存順で
  並列処理し、child は integration branch まで自動マージしたいが、
  default branch への自動マージは避けたいとき。
---

# Issue Graph Orchestrator

## Overview

この skill は、親 Issue に書かれた child issue 群を dependency graph として扱い、
`gh-issue-resolver` を lane worker として並列実行する上位 orchestrator である。

安全性の核は、child lane の merge target を default branch ではなく
orchestrator 専用の integration branch に固定することにある。
この skill は child を integration branch へ自動マージしてよいが、
parent PR の自動マージは行わない。

## Invocation Contract

基本形は次の 1 行だけでよい。

```text
$issue-graph-orchestrator https://github.com/org/repo/issues/83
```

この skill は次を暗黙に固定する。

- integration branch 名は `codex/orch/<parent-issue-number>` を既定とする
- child lane は `gh-issue-resolver` を `merge:<integration-branch>` 付きで呼ぶ
- child は integration branch に入った時点で close してよい
- parent は integration branch から default branch 向け PR を作るが、自動 merge しない

## Strong Input Contract (v1)

この skill は v1 では自由入力を受けない。親 Issue には少なくとも次が必要である。

- child issue 一覧
- child issue の dependency graph
- parent の完了条件

graph の source priority は次の順とする。

1. child issue 本文の `blocked by`
2. parent issue の mermaid dependency graph
3. parent issue の child issue 一覧

上位の source と下位の source が矛盾した場合、下位を信用してはいけない。
矛盾は parent issue の blocker として報告し、勝手に graph を推論し直さない。

## Preconditions

開始前に次を確認する。

- parent issue が URL または `owner/repo#number` で指定されている
- child issue が列挙されている
- child issue それぞれに `$gh-issue-reviewer` `APPROVE` 済みの根拠がある
- child lane を複数走らせてもよい repo 権限がある

次に当てはまる場合、この skill は止まる。

- child issue 一覧が無い
- graph が読めない
- child issue の readiness review が無い
- parent issue が単なるメモで、完了条件が無い

## Execution Model

### 1. Parent issue を読む

- parent issue から child issue 一覧と dependency graph を抽出する
- child ごとに status を `blocked`, `ready`, `running`, `merged`, `failed` で持つ

### 2. Integration branch を準備する

- `codex/orch/<parent-issue-number>` を作成または再利用する
- 以後、child lane の merge target はこの branch に固定する
- integration branch の履歴は rewrite しない

### 3. Ready lane を並列起動する

- dependency がすべて解決済みの child だけを `ready` とみなす
- ready child には次の形式で lane を渡す

```text
/gh-issue-resolver <child-issue-number> merge:codex/orch/<parent-issue-number>
```

- lane は reviewer / merger / self-merge まで自走させる
- child issue は integration branch へ merge 完了した時点で close してよい

### 4. Conflict と stale lane を再調停する

通常は lane 自治を優先する。orchestrator が介入するのは次の場合だけでよい。

- merge target 更新後に lane が stale のまま進まない
- conflict を 2 回以上繰り返す
- review `NG` が同じ理由で 2 cycle 以上続く
- lane が依存先の変更で前提崩れを起こした

このとき orchestrator は次の順で対処する。

1. lane に rebase / rerun を促す
2. 必要ならその lane を単独実行へ落とす
3. graph に dependency edge を追加すべきか parent issue に報告する

### 5. Parent PR を作る

- 全 child が `merged` または `done` になったら、integration branch から default branch へ parent PR を作る
- parent PR には child 完了一覧、残留リスク、aggregate verification をまとめる
- parent PR はこの skill では自動 merge しない

### 6. Parent PR gate を通す

- parent PR に対しても `gh-pr-reviewer` は必須とする
- 必要なら `$merger` で merge-ready 判定だけ取ってよい
- ただし merge は人間に委ねる

## Orchestrator Responsibilities

- graph の source of truth を parent issue / child issue から読む
- integration branch を唯一の child merge target として管理する
- ready lane のみを並列起動する
- lane checkpoint を監視する
- stale lane / conflict lane の再調停を行う
- 全 child 完了後に parent PR を作る

## Child Lane Packet

child lane には少なくとも次を渡す。

- child issue URL
- `Execution mode: orchestrated-child`
- `Parent issue`
- `Run id`
- `Requested terminal state: merged`
- `Reporting checkpoints: worktree_ready, pr_opened, review_state_changed, merger_state_changed`
- `merge:<integration-branch>`

## Guardrails

- child lane の merge target は default branch ではなく integration branch に固定する
- child lane の `merge:<branch>` は必須
- child lane が default branch を base に PR を作った場合、orchestrator はその lane を完了扱いにしない
- parent PR は自動 merge しない
- graph の矛盾を勝手に補完しない
- dependency 未解決の child を起動しない
- destructive git 操作をしない

必要なら [references/prompt-examples.md](references/prompt-examples.md) を読む。
