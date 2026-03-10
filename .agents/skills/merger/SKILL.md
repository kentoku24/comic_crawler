---
name: merger
description: >
  de-group 用の PR final merger gate。
  `$gh-pr-reviewer` の承認コメント、review thread 解決状況、
  PR の merge-ready 性を確認し、`APPROVE` または `NG` を PR comment として残す。
  `merge:true` が明示されたときだけ、自身の `APPROVE` 後に PR を merge する。
  Use when: `gh-pr-reviewer` 承認後に「今この PR を人がマージしてよい状態か」を最終判定したいとき、
  または self-merge まで委譲したいとき。
---

# Merger

## Overview

この skill は最終 merger gate であり、「レビュー済みか」ではなく「PR が実際に merge-ready か」を判定する。デフォルトでは merge せず、`merge:true` が明示されたときだけ self-merge を行う。

この repo で `APPROVE` を出してよいのは、少なくとも次をすべて確認できた場合だけとする。

- PR が `OPEN` であり draft ではない
- PR 上に `$gh-pr-reviewer` の `APPROVE` コメントがある
- PR の review thread がすべて resolved である
- GitHub 上の merge-ready 性が blocker なしで確認できる

どれか一つでも未充足、または API 取得失敗などで確認不能なら `NG` を返す。その場合も PR に comment を残して止める。`NG` comment では、**なぜ `NG` 判定なのかを PR Reviewer や実装者が再作業に使える粒度で必ず明示する。**

## Invocation Contract

最小入力は PR 指定だけでよい。

- `Use $merger on <owner/repo#number>`
- `$merger を使って <PR URL> を確認し、merge-ready かを判定して`
- `Use $merger on <owner/repo#number> with merge:true`

この skill は条件確認と判定コメント投稿を内包しているので、追加の手順指定がなくてもこの標準フローで動く。merge は opt-in であり、`merge:true` が packet または invocation に明示されていない限り実行しない。

## Required Evidence

### PR Reviewer approval comment

PR Reviewer の承認は、PR 上に残った comment または review として確認できなければならない。Merger は次を満たす最新の decisive item を approval evidence として扱う。

- body に literal な `$gh-pr-reviewer` が含まれる
- body の最終判断として `APPROVE` または `NG` が明示されている

複数ある場合は、時刻順で最も新しい decisive なものを採用する。最新が `NG` なら merger も `NG`。`APPROVE` が chat 上にしか無い、または PR 上の comment に残っていない場合も `NG`。

### Resolved review threads

review thread の解決状態は GitHub GraphQL の `reviewThreads` で確認する。1 件でも `isResolved=false` が残っていたら `NG`。pagination や API エラーで全件確認できない場合も `確認不能` として `NG`。

### Merge-ready signal

Merger は GitHub 上の merge-ready 性も確認する。少なくとも次を blocker とする。

- PR が `CLOSED`
- PR が draft
- `mergeStateStatus` が `CLEAN` 以外

merge-ready 性を厳密に確認できない場合は楽観せず `NG` とする。

## Workflow

### 1. PR を特定して一次情報を集める

- PR URL または `owner/repo#number` を正規化する。
- `gh pr view` で `state`, `isDraft`, `mergeStateStatus`, `url`, `comments`, `reviews`, `headRefName`, `baseRefName` を取得する。
- GraphQL で `reviewThreads` を取得する。
- 必要なら issue comment と review body を追加で読む。

優先するコマンド:

```bash
gh pr view <pr> --json number,url,state,isDraft,mergeStateStatus,headRefName,baseRefName,comments,reviews
gh api graphql -f query='... reviewThreads ...'
```

### 2. PR Reviewer approval evidence を判定する

- issue comments と reviews の両方から `$gh-pr-reviewer` を含む decisive なものを探す。
- 最新の decisive item が `APPROVE` なら pass。
- 見つからない、最新が `NG`、本文形式が曖昧、PR Reviewer comment と断定できない場合は fail。

### 3. review thread 解決状態を判定する

- `reviewThreads.nodes[*].isResolved` を確認する。
- 1 件でも unresolved があれば fail。
- thread 数が多すぎて全件確認できない場合や API エラー時も fail。

### 4. PR の merge-ready 性を判定する

- PR が `OPEN` であることを確認する。
- PR が draft ではないことを確認する。
- `mergeStateStatus == CLEAN` を確認する。

どれかが fail したら `NG`。`gh-pr-reviewer` 承認と thread 解決だけでは足りず、GitHub 上で merge blocker が見えていないことまで確認する。

### 5. 結果を `APPROVE` / `NG` として PR に残し、そのうえで返す

結果本文は次の形で作る。

```markdown
## Merger Result
- PR state: OPEN | CLOSED
- Draft: no | yes
- PR Reviewer approval comment: ok | missing | latest decision is NG | unconfirmed
- Review threads: all resolved | unresolved (<count>) | unconfirmed
- Merge state: CLEAN | <other> | unconfirmed
- Merge requested: true | false
- Decision: APPROVE | NG
- Reason: ...
- Next action: ...

$merger
APPROVE | NG
```

作成した結果本文は、`APPROVE` / `NG` のどちらでも **必ず `gh pr comment` で PR に投稿する**。特に `NG` のときは、`Reason` を省略してはいけない。

- comment 投稿に成功したときだけ、その判定を merger gate 完了としてよい
- comment 投稿に失敗した場合、chat 上で判定を書けても gate 完了扱いにしてはいけない
- 同じ理由で直近に自分の merger comment がある場合は重複投稿を避ける

### 6. `merge:true` のときだけ self-merge を行う

- `merge:true` が明示されていない場合、merger は `APPROVE` を出しても merge してはいけない。
- `merge:true` が明示され、かつ merger 自身が `APPROVE` を出した場合にだけ `gh pr merge` を実行してよい。
- merge 実行前に、直前に投稿した merger `APPROVE` comment が PR 上に残っていることを確認する。
- merge に失敗した場合は PR に失敗理由を comment し、chat でも失敗を返す。
- merge 成功時は、merge 実行結果を PR URL / merge commit / strategy とともに返す。

優先コマンド:

```bash
gh pr merge <pr> --merge --delete-branch=false
```

## Result Contract

結果は次のいずれかで返す。

```markdown
## Merger Result
- APPROVE
- PR: ...
- Evidence:
  - PR Reviewer comment: ...
  - Review threads: all resolved
  - Merge state: CLEAN
- PR comment posted: yes
- Merge executed: no
```

または

```markdown
## Merger Result
- NG
- Reason:
  - ...
- PR comment posted: yes | no
- Merge executed: no
```

または

```markdown
## Merger Result
- APPROVE
- PR: ...
- Evidence:
  - PR Reviewer comment: ...
  - Review threads: all resolved
  - Merge state: CLEAN
- PR comment posted: yes
- Merge executed: yes
- Merge method: merge
```

## Guardrails

- chat 上の `gh-pr-reviewer` `APPROVE` を、PR comment の代わりに使ってはいけない。
- `$gh-pr-reviewer` comment の本文に decisive な `APPROVE` / `NG` が無ければ approval evidence とみなしてはいけない。
- unresolved review thread を無視して `APPROVE` してはいけない。
- `mergeStateStatus` が `CLEAN` でないのに `APPROVE` してはいけない。
- 前提確認に失敗したのに「たぶん大丈夫」で `APPROVE` してはいけない。
- `NG` のときに blocker や確認不能理由を書かず、結論だけを comment してはいけない。
- `merge:true` が無いのに `gh pr merge` を呼んではいけない。
- merger 自身が `APPROVE` していないのに merge してはいけない。
