---
name: merger
description: >
  comic_crawler 用の PR merger gate。PR 上に `$spacex-chief-reviewer` の
  `APPROVE` コメントが残っていること、全 review thread が resolved であること、
  `Residual Risks` が issue 化され parent issue に紐付いていることを確認し、
  すべて満たせば merge commit で PR をマージする。確認不能または未充足なら
  `Merge NG` として理由を PR にコメントする。Use when: comic_crawler の PR を
  最終ゲートで確認し、条件を満たすときだけ安全にマージしたいとき。
---

# Merger

## Overview

この skill は merge 実行専用の最終 gate であり、「レビュー済みか」ではなく「repo が要求する merge 前提が PR 上で確認できるか」を判定する。

この repo で merge してよいのは、少なくとも次をすべて確認できた場合だけとする。

- PR 上に `$spacex-chief-reviewer` の `APPROVE` コメントがある
- PR の review thread がすべて resolved である
- PR の `Residual Risks` がすべて follow-up Issue 化され、parent issue に sub-issue として紐付いている

どちらか一方でも未充足、または API 取得失敗などで確認不能なら merge してはいけない。その場合は `Merge NG` として理由を PR にコメントし、そこで止める。

## Invocation Contract

最小入力は PR 指定だけでよい。

- `Use $merger on <owner/repo#number>`
- `$merger を使って <PR URL> を確認して、条件を満たすならマージして`

この skill は条件確認と merge 実行を内包しているので、追加の手順指定がなくてもこの標準フローで動く。

## Required Evidence

### Chief Reviewer approval comment

Chief Reviewer の承認は、PR 上に残ったコメントとして確認できなければならない。Merger は次を満たす最新の comment / review を approval evidence として扱う。

- body に literal な `$spacex-chief-reviewer` が含まれる
- body の最終判断として `APPROVE` または `NG` が明示されている

複数ある場合は、時刻順で最も新しい decisive なものを採用する。最新が `NG` なら merge 不可。`APPROVE` が chat 上にしか無い、または PR 上の comment に残っていない場合も merge 不可。

### Resolved review threads

review comment の解決状態は GitHub GraphQL の `reviewThreads` で確認する。1 件でも `isResolved=false` が残っていたら merge 不可。人間・bot を問わず unresolved thread は blocker として扱う。

GraphQL 取得に失敗した場合や、pagination 上限のせいで全件確認できない場合も `確認不能` として merge 不可にする。

### Residual Risk issues

Residual Risk の source of truth は PR body の `Residual Risks` section とする。Merger は次を要求する。

- PR body に明示的な `Residual Risks` section がある
- Risk が存在する場合、各 bullet が issue reference (`#123` または Issue URL) を含む
- 各 referenced issue が存在する
- 各 referenced issue の `parent` が今回の親 issue と一致する

Residual Risks が無い場合は、その section に `None` または同等の明示が必要とする。section 自体が無い場合は `確認不能` 扱いにする。

親 issue は、呼び出し packet で明示された issue を優先し、無い場合だけ PR body 中の `Closes #N` / `Refs #N` / issue URL から推定する。親 issue を一意に確定できない場合は merge 不可。

## Workflow

### 1. PR を特定して一次情報を集める

- PR URL または `owner/repo#number` を正規化する。
- `gh pr view` で `state`, `url`, `body`, `comments`, `reviews`, `headRefName`, `baseRefName` を取得する。
- GraphQL で `reviewThreads` を取得する。
- 必要な issue について `parent` と sub-issue 関係を取得する。
- 必要なら issue comment と review body を追加で読む。

優先するコマンド:

```bash
gh pr view <pr> --json number,url,state,body,headRefName,baseRefName,comments,reviews
gh api graphql -f query='... reviewThreads ...'
gh issue view <issue> --json number,title,parent,url
```

### 2. Chief Reviewer approval evidence を判定する

- issue comments と reviews の両方から `$spacex-chief-reviewer` を含む decisive なものを探す。
- 最新の decisive item が `APPROVE` なら pass。
- 見つからない、最新が `NG`、コメント形式が曖昧、author や本文から chief reviewer comment と断定できない場合は fail。

### 3. review thread 解決状態を判定する

- `reviewThreads.nodes[*].isResolved` を確認する。
- 1 件でも unresolved があれば fail。
- thread 数が多すぎて全件を確認できない場合や API エラー時も fail。

### 4. Residual Risk issue 化を判定する

- PR body の `Residual Risks` section を読む。
- `None` の明示がある場合は pass。
- Risk が列挙されている場合は、各 bullet の issue reference を抽出する。
- 親 issue を確定し、各 referenced issue の `parent` がその issue と一致することを確認する。
- reference が無い、issue が存在しない、parent が一致しない、section が無い、親 issue が一意に確定できない場合は fail。

### 5. 条件を満たさない場合は `Merge NG` を PR にコメントする

- `gh pr comment` で理由を PR に残す。
- コメントには少なくとも次を含める。

```markdown
## Merge NG
- Chief Reviewer approval comment: ok | missing | latest decision is NG | unconfirmed
- Review threads: all resolved | unresolved (<count>) | unconfirmed
- Residual Risk issues: ok | none declared | missing refs | parent mismatch | unconfirmed
- Reason: ...
- Next action: ...
```

- 既存の unresolved thread を勝手に resolve してはならない。
- 同じ理由で直近に自分の `Merge NG` コメントがある場合は重複投稿を避ける。

### 6. 条件を満たす場合だけマージする

- `gh pr merge --merge --delete-branch` を使う。
- merge 実行前に PR が `OPEN` であることを確認する。
- merge コマンドが失敗した場合は、その失敗理由を `Merge NG` として PR にコメントして止める。

この repo では merge commit を使う。

## Result Contract

結果は次のいずれかで返す。

```markdown
## Merge Result
- MERGED
- PR: ...
- Evidence:
  - Chief Reviewer comment: ...
  - Review threads: all resolved
  - Residual Risk issues: all linked to parent issue
```

または

```markdown
## Merge Result
- NG
- Reason: ...
- PR comment posted: yes | no
```

## Guardrails

- chat 上の reviewer `APPROVE` を、PR comment の代わりに使ってはいけない。
- `$spacex-chief-reviewer` comment の本文に decisive な `APPROVE` / `NG` が無ければ approval evidence とみなしてはいけない。
- unresolved review thread を無視して merge してはいけない。
- `Residual Risks` が prose だけで issue reference を持たない状態を見逃してはいけない。
- Residual Risk issue が存在しても parent issue に紐付いていなければ merge してはいけない。
- merge は必ず `--merge` を使い、`--squash` / `--rebase` を使わない。
- 前提確認に失敗したのに「たぶん大丈夫」で merge してはいけない。
