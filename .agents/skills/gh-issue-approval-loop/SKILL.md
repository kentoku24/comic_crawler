---
name: gh-issue-approval-loop
description: >
  親Issueと紐づく子Issue群を implementation-ready に整え、
  各Issueごとに `$gh-issue-reviewer` review を並列で回し、
  全Issueで `APPROVE` が揃うまで Issue 本文を修正し続ける workflow。
  Use when: 親Issueと子Issue群をまとめて review-ready / implementation-ready にしたいとき、
  issue decomposition 後に scope・constraints・non-goals・next action を各 Issue へ揃えたいとき、
  実装着手前に parent + children 全件へ `$gh-issue-reviewer` gate を残したいとき。
---

# Parent/Child Issue Approval Loop

## Overview

この skill は、親 Issue とそれに紐づく子 Issue 群を対象に、各 Issue を implementation-ready に整え、`$gh-issue-reviewer` の `APPROVE` が全件に揃うまで回すための専用 workflow である。

目的は、chat 上の整理ではなく、Issue 自体を実装開始できる粒度へ揃えることだ。結果として各 Issue には少なくとも次が残る。

- 明確な実施範囲
- 制約
- 対象外
- 着手前に解消すべき論点
- 次の行動
- `$gh-issue-reviewer` の `APPROVE` comment

## When To Use

次のいずれかに当てはまるときに使う。

- 親 Issue と子 Issue 一式をまとめて implementation-ready にしたい
- issue 分解までは終わっているが、`$gh-issue-reviewer` を通る粒度に揃っていない
- 子 Issue ごとに parallel lane で review / edit / re-review を回したい

## Inputs

最小入力:

- 親 Issue URL
- 親 Issue 番号
- `owner/repo#number`

任意入力:

- 子 Issue の明示リスト
- canonical docs の場所
- 既知の open questions

親 Issue だけが渡された場合は、親 Issue 本文と comment を source of truth として子 Issue を収集する。

## Workflow

### 1. 対象 Issue 集合を確定する

- 親 Issue を正規化する。
- `gh issue view <issue> --json number,title,body,url,comments` を使い、親 Issue の body と comments を読む。
- 子 Issue は次の順で集める。
  - 親 Issue 本文の `子Issue一覧`
  - `blocked by` / issue 番号参照
  - user が明示した issue list
- 子 Issue の集合が曖昧なら、推測せず user に確認する。

### 2. 各 Issue を implementation-ready 形式へ補強する

各 Issue 本文から、少なくとも次が読み取れる状態にする。

- 実施範囲
- 制約
- 対象外
- 着手前に解消すべき論点
- 次の行動

不足していれば `gh issue edit` で Issue 本文を修正する。最低限の rule は次のとおり。

- scope は 1 issue = 1 bounded unit に保つ
- constraint は canonical docs や依存 Issue と矛盾しないようにする
- non-goals は scope creep を防ぐ粒度で明示する
- open questions が本当に残る場合は無理に `APPROVE` に寄せず `NG` 前提で書く

### 3. Issue ごとに parallel lane を作る

各 Issue は独立 lane として扱う。

- 1 issue = 1 review lane
- lane 間で本文編集対象を重ねない
- 並列化は issue 単位で行い、同じ issue を複数 lane で触らない

multi-agent が使えるときは、issue ごとに別 agent を立ててよい。使えないときは、親セッションが issue ごとの edit / review / re-review を non-overlapping に回す。

### 4. 各 lane で `$gh-issue-reviewer` を回す

各 Issue について `gh-issue-reviewer` workflow を使う。

- `gh issue view` と comment API で一次情報を読む
- 実施範囲 / 制約 / 対象外 / 着手前に解消すべき論点を整理する
- `APPROVE` か `NG` を判定する
- 結果は **必ず** `gh issue comment` で Issue に残す

レビューコメントの最小形は次のとおり。

```markdown
## Issue Review
- 実施範囲:
  - ...
- 制約:
  - ...
- 対象外:
  - ...
- 着手前に解消すべき論点:
  - none | ...
- 実装開始可否: APPROVE | NG
- 次の行動: ...

$gh-issue-reviewer
APPROVE | NG
```

### 5. `NG` が出た lane だけ修正して再レビューする

- `NG` comment から不足論点を抽出する
- Issue 本文を `gh issue edit` で修正する
- 同じ lane で再度 `$gh-issue-reviewer` を実行する
- `APPROVE` が出るまで繰り返す

修正時の方針:

- user の元意図を超えて scope を広げない
- blocker が残るなら `none` にせず、そのまま Issue に残す
- parent/child の依存関係は壊さない

### 6. parent + children 全件 `APPROVE` で完了する

完了条件:

- 親 Issue に `$gh-issue-reviewer` `APPROVE` comment がある
- 全子 Issue に `$gh-issue-reviewer` `APPROVE` comment がある
- 本文が implementation-ready 形式に揃っている
- 必要なら親 Issue の依存関係図 / 子 Issue 一覧が最新になっている

## Commands

優先コマンド:

```bash
gh issue view <issue> --json number,title,body,url,comments
gh api repos/<owner>/<repo>/issues/<number>/comments --paginate
gh issue edit <issue> --body-file <file>
gh issue comment <issue> --body-file <file>
```

探索補助:

```bash
rg -n "子Issue|blocked by|#<number>" .
```

## Guardrails

- source of truth は Issue 本文と Issue comments に置く
- 本文を修正しても、依存 Issue 番号や親子関係を壊さない
- 実装内容そのものは書き込みすぎず、実装開始できる粒度に留める
- blocker が残る場合は無理に `APPROVE` にしない
- parent は tracking issue のままでよく、無理に単独実装 issue に変換しない
- parallel は issue 単位に限定し、同一 issue を二重に更新しない

## Return Format

chat では少なくとも次を返す。

- 対象 Issue 一覧
- 各 Issue の最終状態: `APPROVE` / `NG`
- `NG` が残る場合は残課題
- 本文を修正した Issue の一覧
- reviewer comment を投稿したこと
