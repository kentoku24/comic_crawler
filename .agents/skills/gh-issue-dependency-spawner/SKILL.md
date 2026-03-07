---
name: gh-issue-dependency-spawner
description: >
  comic_crawler の Epic / 管理 Issue を起点に、依存関係つき sub-issue 群を
  dependency wave ごとに並列 Spawn するオーケストレーション skill。
  親セッションは実装・編集・PR 操作を行わず、ready な sub-issue ごとに
  `$gh-issue-maker-chief-engineer-loop` を使う child agent を起動して待機する。
  Use when: #6 のように sub-issue と依存関係が整理された GitHub Issue を入力に、
  dependency order を守りながら可能な限り並列で処理したいとき。
---

# GitHub Issue Dependency Spawner

## Overview

この skill の責務は orchestration だけに限定する。親セッションは dependency graph を読み、
ready な sub-issue を wave ごとに Spawn し、各 wave の完了を待って次へ進める。

親セッションは次をしてはならない。

- 実装
- ファイル編集
- テストや lint の実行
- PR 作成や更新
- issue の仕様判断

それらはすべて child agent に委譲する。

## Preconditions

次を満たすときだけこの skill を使う。

- 対象は comic_crawler の GitHub Issue である
- 親 Issue に child issue 一覧がある
- 親 Issue か child issues から dependency graph を復元できる
- `$gh-issue-maker-chief-engineer-loop` が使える
- native な agent spawn が使える

agent spawn が使えない場合は、この skill を擬似実行してはならない。親セッションだけで実装に入らず、そこで止まる。

## Inputs

入力は次のいずれかでよい。

- Issue URL
- `owner/repo#number`
- `#number`

`#number` を受け取った場合は、現在の repo を `gh repo view` で解決する。

## Core Workflow

### 1. Parent issue を wave plan に変換する

まず補助スクリプトを実行する。

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_plan.py <issue>
```

このスクリプトは次を返す。

- child issues
- closed issues
- dependency edges
- ready な current wave
- 後続 wave
- child agent に渡す `spawn_prompt`

`warnings` があり、dependency graph を安全に解釈できないときは止まる。推測で順序を決めてはならない。

### 2. Current wave だけを Spawn する

current wave にある issue ごとに、child agent を 1 つずつ Spawn する。
同じ wave の issue は、互いに blocker がないので可能な限り並列で Spawn してよい。

child agent には、スクリプトが返した `spawn_prompt` をそのまま使う。
文面は次の 2 行から変えてはならない。

```text
$gh-issue-maker-chief-engineer-loop を使ってこの Issue を進めてください。
https://github.com/kentoku24/comic_crawler/issues/XX
```

親セッションが child agent に追加の設計判断や実装指示を足してはいけない。

### 3. Wave 完了まで待つ

Spawn 後は、その wave の child agent がすべて終わるまで待つ。

親セッションがやることは次だけである。

- child agent の完了を待つ
- success / blocked / failed を記録する
- 成功した issue をこの orchestration run の中で completed とみなす

child が blocked / failed になったら、そこに依存する downstream issue は Spawn しない。
親セッション自身が詰まりを解こうとしてはいけない。

### 4. 次の ready wave に進む

前の wave が全件 success なら、次の ready wave を Spawn する。
これを pending issue がなくなるまで繰り返す。

この skill における completion 判定は次の通り。

- run 開始前に GitHub 上で `CLOSED` の issue は completed
- 現在の run 中に child agent が success で終わった issue も provisional completed

fresh session で再開するときは GitHub state だけが引き継がれる。merge や close を厳密な完了シグナルにしたい場合は、前 wave の反映後にこの skill を再実行する。

## Commands

### Plan を出す

```bash
python3 .agents/skills/gh-issue-dependency-spawner/scripts/issue_dependency_plan.py https://github.com/kentoku24/comic_crawler/issues/6
```

### Parent issue を読む

```bash
gh issue view 6 --repo kentoku24/comic_crawler --json number,title,body,url,state
```

## Guardrails

- 親セッションは orchestrator であり worker ではない
- parallelize してよいのは同一 wave の issue だけ
- dependency edge が曖昧、欠落、循環している場合は止まる
- 1 child agent = 1 issue を守る
- closed issue は skip する
- child issue の prompt は script 出力を verbatim で使う
- 同じ issue を 2 回 Spawn しない
- downstream issue を blocker 解消前に先回り Spawn しない

## Output Expectations

最初に次を短く共有する。

- parent issue
- closed issues
- current wave
- future waves

各 wave 完了時は次だけ共有する。

- success issues
- blocked / failed issues
- 次に Spawn する wave

最後は次をまとめる。

- completed in this run
- already closed before start
- blocked / failed
- まだ残っていて次回に持ち越す issue
