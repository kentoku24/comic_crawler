---
name: gh-pr-spacex-chief-engineer-review
description: >
  GitHub の指定 PR を `spacex-chief-engineer` の観点でレビューし、加えて
  (1) PR Description に書かれた実現事項が差分・テスト・挙動から確認できるか、
  (2) `spacex-chief-engineer` が過去の Comment で指摘した内容が現在の PR で
  解消されているかを判定する。Use when: PR URL や PR 番号を受けてマージ前レビューを
  したいとき、Description と実装の整合性を確認したいとき、過去の chief engineer
  指摘の解消状況を再点検したいとき。
---

# GitHub PR Chief Engineer Review

## Overview

指定 PR を「これは実際に動くか」の観点でレビューし、マージ判断に必要な追加検証までまとめて返す。`spacex-chief-engineer` スキルが使える環境では必ず先にその指針を読み、使えない場合も同じ原則で評価する。

## Workflow

### 1. PR を特定して一次情報を集める

- PR URL または `owner/repo#123` を正規化する。
- `title`, `body`, `baseRefName`, `headRefName`, changed files, commits, reviews を取得する。
- 差分を読み、重要ファイルはローカルでも開いて確認する。
- 実行可能な検証コマンドが分かる場合だけ、最小限のテストや lint を追加で走らせる。

優先するコマンド:

```bash
gh pr view <pr> --json number,title,body,url,baseRefName,headRefName,files,commits,reviews
gh pr diff <pr>
gh api repos/<owner>/<repo>/issues/<number>/comments --paginate
gh api repos/<owner>/<repo>/pulls/<number>/comments --paginate
```

必要なら GraphQL や `gh pr view --comments` で補完し、review comment と issue comment の両方を見る。

### 2. `spacex-chief-engineer` の基準でレビューする

- 判断軸は「プロセスが正しいか」より「これは実際に動くか」を優先する。
- 指摘はノイズを抑え、高シグナルなものだけを返す。
- 優先順位は `正確性 / 安全性 / データ整合性 / 既存契約との互換性 / 運用リスク / 必須テスト` の順で置く。
- 指摘には必ず `問題`, `影響`, `代替案` を含める。
- マージを止めるべきなら、その理由を明示する。

### 3. PR Description の実現事項を検証する

- Description から「この PR で実現すること」を明示的な文だけ抽出する。
- 箇条書き、見出し、チェックリスト、受け入れ条件を優先し、曖昧な表現は約束として扱わない。
- Description が空、または約束が読み取れない場合は `明示的な実現事項なし` と記録する。
- 各項目を `差分`, `テスト`, `実装箇所`, `説明コメント` に対応づける。
- 各項目を次のいずれかで判定する。
  - `実現済み`
  - `部分実現`
  - `根拠不足`
  - `未実現`
- Description に重要な仕様変更や制約が書かれていない場合は、その不足自体を指摘する。

### 4. `spacex-chief-engineer` の過去 Comment の解消状況を確認する

- author 名、本文、定型句から `spacex-chief-engineer` 由来の comment を特定する。
- 特定の優先順は `reviewer / author の識別子` → `comment 本文の署名や skill 名` → `問題 / 影響 / 代替案` の chief-engineer 定型とする。
- 同じ論点に対する重複 comment は一つの論点に束ねる。
- 各論点について、最新のコード、テスト、返信スレッドを見て現在の状態を再判定する。
- GitHub 上で thread が resolved でも、コード上の問題が残るなら `未解消` と扱う。
- 各論点を次のいずれかで判定する。
  - `解消`
  - `一部解消`
  - `未解消`
  - `確認不能`
- 過去の chief engineer comment が存在しない場合は、その旨を明示する。

### 5. 結果を findings-first で返す

レビュー結果は次の順で返す。

```markdown
## Findings
- [P1] [path:line] 問題: ... 影響: ... 代替案: ...

## Description Check
- 「Description の約束」: 実現済み | 部分実現 | 根拠不足 | 未実現
  - 根拠: 差分 / テスト / コメント

## Chief Engineer Comment Resolution
- 「過去の指摘内容」: 解消 | 一部解消 | 未解消 | 確認不能
  - 根拠: 現在のコード / テスト / スレッド

## Residual Risks / Test Gaps
- 残留リスクや未確認事項
```

レビュー依頼が「コメント投稿込み」でない限り、GitHub への書き込みは行わずチャットで返す。重大な指摘がなければ、そのことを明示したうえで残留リスクとテストギャップだけを返す。

## Guardrails

- Description の文面を鵜呑みにせず、必ず実装とテストで裏を取る。
- Comment の status は GitHub UI ではなく現在のコードを正とする。
- 既存の unrelated な問題は、今回の PR で悪化していない限り広げない。
- 根拠が薄い推測は `確認不能` として扱い、断定しない。
