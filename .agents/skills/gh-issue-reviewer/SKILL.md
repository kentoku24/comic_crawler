---
name: gh-issue-reviewer
description: >
  GitHub Issue の実装開始可否を判定する Issue Reviewer。
  実施範囲、制約、対象外、着手前に解消すべき論点を整理し、
  実装を始めてよいかを `APPROVE` / `NG` で判断する。
  Use when: GitHub Issue URL/番号を受けて実装開始前に範囲と制約を固めたいとき、
  `$gh-issue-resolver` の入口条件を満たす issue review を残したいとき、
  旧 `spacex-chief-engineer` が担っていた issue review を明示的に使いたいとき。
---

# Issue Reviewer

## Overview

この skill は、Issue を実装に渡してよい状態かを判定する。目的は設計を広げることではなく、Issue を実装開始できる状態にすることだ。

Issue Reviewer は、Issue から実施範囲、制約、対象外、着手前に解消すべき論点を抽出し、そのまま `maker` や `$gh-issue-resolver` が使える形に整理する。これは、旧 `spacex-chief-engineer` が Issue 開始前に担っていた見極めを、Issue Reviewer という名前で明示したものだ。判断は chat 上の感想ではなく、Issue 自体に残る監査可能な記録として `APPROVE` または `NG` をコメントに残す。

## Invocation Contract

最小入力は Issue 指定だけでよい。

- `Use $gh-issue-reviewer on <owner/repo#number>`
- `$gh-issue-reviewer を使って <Issue URL> の実装開始可否を見て`

この skill は workflow を内包しているので、Issue が渡されたら標準フローで開始可否の確認を行う。

## Workflow

### 1. Issue の一次情報を集める

- Issue URL または `owner/repo#number` を正規化する。
- `gh issue view` と comment API で body / comments / labels / metadata を読む。
- 既存の説明、要求、補足コメントから実装に必要な論点を抽出する。

優先するコマンド:

```bash
gh issue view <issue> --json number,title,body,url,labels,comments
gh api repos/<owner>/<repo>/issues/<number>/comments --paginate
```

### 2. Issue の要点を整理する

- 実施範囲: 今回実装で満たす約束
- 制約: 守るべき前提、制限、広げない範囲
- 対象外: 今回やらないこと
- 着手前に解消すべき論点: 実装開始前に解消が必要な曖昧さや不足

Issue 本文とコメントから十分な根拠を引けない場合は、楽観せず着手前に解消すべき論点に入れる。

### 3. 実装開始可否を判定する

- `APPROVE` は、実施範囲と制約が実装に渡せる粒度で固まっているときだけ出す。
- `NG` は、範囲が曖昧、制約が不足、受け入れ条件が不足、または blocker が残る場合に出す。
- `NG` の場合は、何を補えば `APPROVE` に進めるかを次の行動として明示する。

`APPROVE` の最低条件:

- 実施範囲が説明できる
- 制約と対象外が説明できる
- 実装開始を妨げる論点が主要論点として整理されている、または解消済みである
- `maker` または `$gh-issue-resolver` に渡せる粒度の要点になっている

### 4. 結果を Issue に残し、そのうえで返す

結果本文は次の形で作る。

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

作成した結果本文は、`APPROVE` / `NG` のどちらでも **必ず `gh issue comment` で Issue に投稿する**。コメントには少なくとも次を含める。

- literal な `$gh-issue-reviewer`
- 実施範囲 / 制約 / 対象外 / 着手前に解消すべき論点
- 最終行の `APPROVE` または `NG`

- コメント投稿に成功したときだけ、その判定を issue review 完了としてよい
- コメント投稿に失敗した場合、chat 上で判定を書けても完了扱いにしてはいけない

chat には、Issue に投稿した本文とコメント済みであることを明示して返す。

## Guardrails

- Issue 本文とコメントを source of truth として扱う。
- 実装開始可否は実装に渡せる粒度で判定する。
- blocker が残る場合は `NG` とし、次の行動を返す。
- 判定は Issue 上のコメントを根拠とする。
