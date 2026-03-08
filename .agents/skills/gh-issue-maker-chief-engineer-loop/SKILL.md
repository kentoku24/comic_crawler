---
name: gh-issue-maker-chief-engineer-loop
description: >
  GitHub Issue を起点に、既に Chief Engineer レビュー済みの実装タスクを
  Codex で回す専用ループ。指定 Issue から accepted scope と制約を抽出し、
  独立した作業単位ごとに `maker` エージェントを必要に応じて並列起動して実装し、
  親セッションで統合して PR を作成または更新し、その PR を
  `$spacex-chief-reviewer` でレビューし、最後に `$merger` で merge まで進める。
  reviewer または merger が NG を返したら指摘を次の maker work packet に落として
  再実装し、マージされるまで繰り返す。Use when:
  GitHub Issue URL/番号だけを渡して作業を開始したいとき、Issue に既存の Chief
  Engineer レビューがあるとき、実装から PR 更新、`$spacex-chief-reviewer`
  による再レビュー、`$merger` による merge までを標準ループで自動的に進めたいとき。
---

# GitHub Issue Maker / Chief Reviewer / Merger Loop

## Overview

`codex-mission-control` の派生版として、Issue 起点の実装ループだけに責務を絞る。親セッションが Mission Planner と Mission Control を兼務し、実装は原則 `maker` が担い、PR gate は `$spacex-chief-reviewer` と `$merger` が担う。

Issue に既存の Chief Engineer レビューがある前提で始め、`maker` が実装し、親セッションが結果を統合して PR を作成または更新し、その PR を `$spacex-chief-reviewer` が review gate として判定し、`$merger` が merge gate と実マージを担当する。reviewer または merger が `NG` を返した場合は、その指摘を次 cycle の maker packet に変換して再実装または PR 状態の修正を行う。

`orchestrated-child` では、PR 作成や reviewer `APPROVE` は途中 checkpoint にすぎない。
親 orchestrator が lane を追跡できるよう、child は `worktree_ready`, `pr_opened`, `review_state_changed`, `merged`, `issue_closed` を structured に報告し、requested terminal state を満たすまで走り切るか、未達なら pending state を返す。

この skill には 2 つの完了モードがある。

- `standalone`: reviewer gate が `APPROVE` になり、merger gate を通って PR が実際に merge された時点でこの skill は完了してよい
- `orchestrated-child`: 親 orchestrator から terminal state が指定されている。reviewer `APPROVE` は中間状態であり、merge / issue close まで追うか、少なくとも `merge_pending` を返して親に control を戻す

この loop でいう review / merge gate は、**親セッションや maker と別 agent の context で reviewer / merger が判定したときだけ有効**とする。親セッションが reviewer や merger の手順を自己適用して得た結論は、evidence 整理や事前点検には使えても gate 完了には数えない。

この skill は、呼び出し時に進め方を毎回指定しなくてよい。Issue を指定されたら、この標準ループをデフォルト動作として実行する。

## Preconditions

この skill を使う前に次を満たしていることを確認する。

- GitHub Issue が URL または `owner/repo#number` で指定されている。
- Issue body または comment から、既存の Chief Engineer レビュー内容を確認できる。
- Issue に、少なくとも最低限の scope と acceptance criteria がある。
- 実装を 1 つ以上の bounded packet に分けられる。

次に当てはまる場合は、この skill を使わずに止める。

- Issue が未指定。
- Chief Engineer レビュー済みである根拠を確認できない。
- 変更が極小で、single-pass 実装のほうが安全で速い。
- Issue 自体が探索段階で、accepted scope が未確定。

## Parent Session Responsibilities

親セッションは `codex-mission-control` と同様に Mission Planner と Mission Control を兼務するが、この skill では責務を次に限定する。

- Issue を唯一の source of truth として読み解く。
- cycle ごとの target と packet 分割を決める。
- `maker` の並列実行可否を判断する。
- maker の成果を統合し、必要な verification を走らせる。
- 統合した変更から PR を作成または既存 PR を更新する。
- `$spacex-chief-reviewer` を**別 agent**として起動し、PR review packet を渡し、`APPROVE` か `NG` を受け取る。
- reviewer に、chat 上の判定だけでなく PR 上へ `$spacex-chief-reviewer` 署名付きの gate comment を残させる。
- reviewer `APPROVE` 後に `$merger` を**別 agent**として起動し、merge gate と実マージを委譲する。
- reviewer または merger の `NG` を、次 cycle の maker packet または PR hygiene 作業に変換する。

`explorer` や `telemetry` は常用しない。対象ファイルが広すぎて file mapping ができない場合だけ `explorer` を補助的に使い、検証が複雑で maker の自己検証だけでは不十分な場合だけ `telemetry` を追加する。

詳細な packet 形式が必要なときは [references/templates.md](references/templates.md) を読む。
実際の呼び出し文面が必要なときは [references/prompt-examples.md](references/prompt-examples.md) を読む。

## Invocation Contract

最小入力は Issue 指定だけでよい。

- `Use $gh-issue-maker-chief-engineer-loop on <owner/repo#number>`
- `$gh-issue-maker-chief-engineer-loop を使って <Issue URL> を進めて`

上のような短い指定を受けたら、workflow の詳細を user に確認し直さず、この skill の標準 loop を採用する。

親 orchestrator から渡される packet では、次の追加情報が入ってよい。

- `Execution mode: orchestrated-child`
- `Parent issue`
- `Run id`
- `Existing PR`
- `Existing branch / worktree`
- `Requested terminal state`

これらがある場合は、standalone ではなく orchestrated-child として扱う。

## Orchestrated Child Reporting Contract

`orchestrated-child` のときは、親 orchestrator に「生存確認」ではなく lane checkpoint を返す。
heartbeat は completion ではない。少なくとも次の checkpoint で `Cycle Update` を返す。

- `worktree_ready`: branch / worktree / session が固まった
- `pr_opened`: open PR URL / number が確定した
- `review_state_changed`: `pending`, `changes_requested`, `approved` のいずれかに変わった
- `merged`: closing PR が default branch に merge された
- `issue_closed`: issue close を確認した

heartbeat には少なくとも次を含める。

- current checkpoint
- branch
- worktree
- PR
- blockers
- next move
- terminal result が `in_progress` なのか `merge_pending` / `issue_close_pending` / `done` なのか

親 orchestrator が resume できるよう、曖昧な「ほぼ終わり」「PR を出したので完了」は禁止する。

親 orchestrator が `merged closing PR on default branch and issue closed` を要求している場合、child はその terminal state を満たすまで lane owner の責務を持つ。
権限不足、merge blocker、外部判断待ちのときだけ `merge_pending`, `issue_close_pending`, `blocked` として制御を返す。

## Workflow

### 1. Issue 指定で開始する

- Issue を URL または `owner/repo#number` で正規化する。
- `gh issue view` と必要なら comment API で body / comments / labels / metadata を読む。
- 既存の Chief Engineer レビューから、accepted scope, constraints, non-goals, blocking concerns を抽出する。
- 抽出結果を `Issue Brief` にまとめる。

Chief Engineer レビュー済みの証拠が見つからなければ、maker loop を開始しない。その場合は「先に chief-engineer review が必要」として停止する。

### 2. Maker work packet に分割する

- Issue Brief をもとに、独立した実装単位へ分割する。
- 各 packet は「1 つの明確な成果物」だけを持つように小さく保つ。
- packet ごとに `Objective`, `Relevant files`, `Constraints`, `Deliverable`, `Stop conditions` を定義する。
- 並列化は、変更ファイルの ownership が分離できる場合だけ許可する。

次に当てはまる場合は parallel maker を使わない。

- 同じファイルや同じ関数を複数 packet が触る。
- 変更順序に強い依存がある。
- まだ設計の一貫性を親セッションが固めきれていない。

### 3. Maker をエージェントとして適宜並列で立ち上げる

- 各 maker には、自分の packet に必要な最小限の context だけを渡す。
- maker は packet 外の scope を広げない。
- maker は実装に加えて、最小限の確認コマンドを実行し、変更点と gaps を報告する。
- 親セッションは maker outputs を統合し、競合や抜けを解消する。

maker への指示では、少なくとも次を明示する。

- Issue の何を満たす packet か
- 触ってよいファイル境界
- 守るべき Chief Engineer 制約
- 終了条件
- 実行してほしい確認コマンド

### 4. 親セッションで統合して PR を作成または更新する

- maker outputs を親セッションで統合し、conflict や抜けを解消する。
- verification evidence を整理して、PR body に反映できる状態にする。
- 既存 PR があればその PR を更新し、なければ新規 PR を作成する。
- PR には少なくとも `Issue`, `変更概要`, `検証結果`, `残留リスク` を含める。

PR の扱いは次を原則とする。

- 同じ Issue に対応する open PR があれば更新を優先する。
- 対応 PR が無ければ、親セッションが作業ブランチから新規 PR を作成する。
- maker ごとに PR を分けず、親セッションが統合した単位で 1 つの PR にまとめる。

`orchestrated-child` では、PR 作成後に終わらない。
同じ lane で review comment 対応、merge follow-up、issue close 確認まで進めるのがデフォルトである。

### 5. PR を `$spacex-chief-reviewer` でレビューする

- 親セッションは `spawn_agent` などで `$spacex-chief-reviewer` を**別 agent / 別 thread**として起動する。
- reviewer agent には `fork_context=false` を優先し、親セッションの実装 reasoning を丸ごと渡さず、PR URL、統合後の diff, changed files, test evidence, known gaps など review に必要な最小限の packet だけを渡す。
- reviewer は計画ではなく、PR 上の実装済み差分をレビューする。
- reviewer は `spacex-chief-reviewer` の標準フローで review を行い、`APPROVE` か `NG` を返す。
- reviewer には、chat 上の判定に加えて PR 上へ gate comment を残すことを明示的に要求する。comment には literal な `$spacex-chief-reviewer` と、最終行の `APPROVE` または `NG` を含めさせる。
- 曖昧な「ほぼよい」「条件付きでよい」は `NG` として扱い、再作業項目へ落とす。
- 親セッションが reviewer skill を自分でなぞっても、それは gate ではなく preflight review に留まる。**別 agent の判定が返るまで cycle は完了しない。**
- reviewer が chat では `APPROVE` を返しても、PR comment を残していなければ merge gate に進めてはいけない。

reviewer への packet には次を含める。

- 元 Issue の accepted scope
- PR URL
- 既存 Chief Engineer guidance
- 今 cycle で変更した内容
- 検証結果
- 既知の未解決事項
- 今回求める gate 判定
- PR に残すべき gate comment 形式

別 agent reviewer を起動できない場合:

- 親セッションは PR 作成・evidence 整理までは進めてよい。
- ただし `APPROVE` 扱いで完了してはいけない。
- 状態は `reviewer gate pending` または `degraded: reviewer unavailable` として止める。

### 6. `APPROVE` 後に `$merger` を実行する

- 親セッションは reviewer の PR comment を確認したあと、`$merger` を**別 agent / 別 thread**として起動する。
- merger agent には PR URL と、chief reviewer が残した gate comment が prerequisite であることを渡す。
- merger は次を確認する。
  - PR 上に `$spacex-chief-reviewer` の `APPROVE` comment がある
  - PR の review thread がすべて resolved である
- merger は条件を満たさない、または確認不能な場合、PR に `Merge NG` コメントを残して `NG` を返す。
- merger は条件を満たした場合だけ `gh pr merge --merge --delete-branch` で merge する。
- 親セッションや reviewer が merger の手順を自己適用しても、それは merge gate ではない。

merger への packet には次を含める。

- PR URL
- chief reviewer comment の期待形式
- merge に使う strategy (`--merge`)
- unresolved review thread は blocker であること
- 今回求める merge gate 判定

別 agent merger を起動できない場合:

- 親セッションは reviewer gate 完了までは進めてよい。
- ただし merge 完了扱いにしてはいけない。
- 状態は `merger gate pending` または `degraded: merger unavailable` として止める。

### 7. reviewer または merger が `NG` なら戻る

- reviewer / merger の `NG` を論点ごとに分解する。
- コード修正が必要な論点は、次 cycle の maker packet に落とし込む。
- review thread resolve や reviewer comment 追記のような PR hygiene だけが不足している場合は、親セッションがその不足を解消して 5 または 6 に戻ってよい。
- scope creep を防ぐため、Issue の外に広がった rework は切り離す。
- PR は閉じず、同じ PR を更新し続けることを基本とする。
- 同じ理由で 2 cycle 連続 `NG` になったら、packet の切り方か設計前提が悪い可能性が高い。親セッションが loop を止め、Issue Brief を再構成する。

### 8. merge 完了で終了する

`APPROVE` の意味は execution mode で変わる。

- `standalone`: この step の条件を満たせば完了してよい
- `orchestrated-child`: `APPROVE` は merge / issue close phase への遷移条件であり、まだ完了ではない

次をすべて満たしたときだけ完了とする。

- **別 agent として起動された** `$spacex-chief-reviewer` が `APPROVE` を返した。
- その reviewer が、PR 上へ `$spacex-chief-reviewer` 署名付きの `APPROVE` comment を残している。
- **別 agent として起動された** `$merger` が merge 条件を確認し、PR を実際にマージした。
- 対応 PR が作成済みまたは最新状態に更新済みである。
- Issue の acceptance criteria が evidence 付きで満たされている。
- main regression risk と test gaps が明示されている。
- 親セッションが、Issue のどの約束をどの変更で満たしたか説明できる。

`orchestrated-child` の場合、さらに次を満たしたときだけ `done` とみなす。

- closing PR が default branch に merge 済み、または親 orchestrator が同等の delivery evidence を明示的に受け入れている
- issue が `CLOSED`

reviewer `APPROVE` 後に merge や issue close が未完了なら、この skill は `success` と言わず、`merge_pending` または `issue_close_pending` として親へ返す。
ただし repo 権限や merge blocker が解消できるなら、そのまま merge / close まで進めることを優先する。

## Tooling Guidance

優先するコマンド:

```bash
gh issue view <issue>
gh api repos/<owner>/<repo>/issues/<number>/comments --paginate
gh pr view <pr>
gh pr create
gh pr edit <pr>
gh pr comment <pr>
gh pr merge <pr> --merge --delete-branch
gh api graphql -f query='... reviewThreads ...'
rg --files
rg <pattern>
```

追加方針:

- 実装編集は `apply_patch` を使う。
- discovery は `rg` を優先する。
- maker が走らせる確認は、broad なフルテストより、packet に紐づく focused check を優先する。
- PR 操作は親セッションが行う。maker に PR 作成や更新を任せない。
- `$spacex-chief-reviewer` review 前に、親セッションが最低限の integration check を行う。
- reviewer gate と merger gate は親セッションではなく、別 agent 起動で実行する。

## Guardrails

- Issue に書かれていない新要求を勝手に acceptance criteria に追加しない。
- reviewer が `NG` を返したら、そのまま完了扱いにしない。
- 並列 maker に同一 ownership の変更を配らない。
- maker が返した「done」を鵜呑みにせず、親セッションが evidence を確認する。
- PR は parent-owned artifact として扱い、子エージェントに ownership を分散しない。
- PR gate は必ず `$spacex-chief-reviewer` を通し、review は実コードと検証結果に対して行い、口頭の説明だけで通さない。
- reviewer の chat 上の `APPROVE` だけを根拠に merge してはいけない。PR 上の `$spacex-chief-reviewer` comment が必要。
- merge は必ず `$merger` を通し、unresolved review thread が 1 件でも残っている状態で進めてはいけない。
- 親セッションの自己レビューや reviewer checklist の自己適用を、`APPROVE` / `NG` gate とみなしてはいけない。
- reviewer gate と merger gate は必ず実装 agent と別 context で行い、別 agent を起動できない場合は completion ではなく pending / degraded として止める。
- `orchestrated-child` では reviewer `APPROVE` だけで `done` を返してはいけない。
- `orchestrated-child` では PR 作成だけで `success` を返してはいけない。
- `orchestrated-child` の heartbeat は non-terminal report であり、session 完了と混同してはいけない。
- 親が full-auto orchestration を期待しているとき、child は「人が次に聞いたら続ける」という前提で止まってはいけない。
- この skill は「Issue 起点の実装 loop」に特化している。探索が主目的なら `$codex-mission-control` に戻る。
