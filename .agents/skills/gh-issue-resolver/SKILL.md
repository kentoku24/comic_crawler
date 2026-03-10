---
name: gh-issue-resolver
description: >
  GitHub Issue を起点に、実装タスクを Codex で回す専用ループ。
  指定 Issue から accepted scope と制約を抽出し、
  独立した作業単位ごとに `maker` エージェントを必要に応じて並列起動して実装し、
  親セッションで統合して PR を作成または更新し、その PR を
  `$gh-pr-reviewer` でレビューし、最後に `$merger` で
  final gate を判定する。`gh-pr-reviewer` または merger が NG を返したら
  指摘を次の maker work packet に落として再実装し、merger が `APPROVE`
  を返すまで繰り返す。Use when:
  GitHub Issue URL/番号だけを渡して作業を開始したいとき、Issue に既存の
  `$gh-issue-reviewer` または legacy `$spacex-chief-engineer` review があるとき、
  実装から PR 更新、`$gh-pr-reviewer`
  による再レビュー、`$merger` による final gate 判定までを標準ループで
  自動的に進めたいとき。
---

# GitHub Issue Loop

## Overview

この skill は、Issue を起点に実装を進め、PR を更新し、`$gh-pr-reviewer` と `$merger` の gate 完了まで到達させるための実行ループである。実装は原則 `maker` が担い、親セッションが統合と進行を担う。

Issue を`maker` が実装し、親セッションが結果を統合して PR を作成または更新し、その PR を `$gh-pr-reviewer` が PR Reviewer gate として判定し、`$merger` が final gate として「人が今マージしてよい状態か」を判定する。`gh-pr-reviewer` または merger が `NG` を返した場合は、その指摘を次 cycle の maker packet に変換して再実装または PR 状態の修正を行う。

この skill は **PR を作って終わらず、`gh-pr-reviewer` `APPROVE` で終わらない**。デフォルトの完了条件は、PR が更新済みで、`$gh-pr-reviewer` と `$merger` の両方から PR 上に `APPROVE` コメントが残り、PR が merge-ready と説明できる状態に到達することだ。`merge:true` を明示した packet だけは、`$merger` が `APPROVE` 後に実際の merge を行ってよい。

`orchestrated-child` では、PR 作成や `gh-pr-reviewer` `APPROVE` は途中 checkpoint にすぎない。親 orchestrator が lane を追跡できるよう、child は `worktree_ready`, `pr_opened`, `review_state_changed`, `merger_state_changed` を structured に報告し、requested terminal state を満たすまで走り切るか、未達なら pending state を返す。

この loop でいう PR review / merger gate は、**親セッションや maker と別 agent の context で `gh-pr-reviewer` / merger が判定したときだけ有効**とする。親セッションが `gh-pr-reviewer` や merger の手順を自己適用して得た結論は、evidence 整理や事前点検には使えても gate 完了には数えない。

この skill は、呼び出し時に進め方を毎回指定しなくてよい。Issue を指定されたら、この標準ループをデフォルト動作として実行する。

## Preconditions

この skill を使う前に次を満たしていることを確認する。

- GitHub Issue が URL または `owner/repo#number` で指定されている。
- Issue body または comment から、既存の `$gh-issue-reviewer` または legacy `$spacex-chief-engineer` review 内容を確認できる。
- Issue に、少なくとも最低限の scope と acceptance criteria がある。
- 実装を 1 つ以上の bounded packet に分けられる。

次に当てはまる場合は、この skill を使わずに止める。

- Issue が未指定。
- `$gh-issue-reviewer` または legacy `$spacex-chief-engineer` review 済みである根拠を確認できない。
- 変更が極小で、single-pass 実装のほうが安全で速い。
- Issue 自体が探索段階で、accepted scope が未確定。

## Parent Session Responsibilities

親セッションの責務は次に限定する。

- Issue を唯一の source of truth として読み解く。
- cycle ごとの target と packet 分割を決める。
- `maker` の並列実行可否を判断する。
- maker の成果を統合し、必要な verification を走らせる。
- 統合した変更から PR を作成または既存 PR を更新する。
- `$gh-pr-reviewer` を**別 agent**として起動し、PR review packet を渡し、`APPROVE` か `NG` を受け取る。
- PR Reviewer に、chat 上の判定だけでなく PR 上へ `$gh-pr-reviewer` 署名付きの gate comment を残させる。
- `gh-pr-reviewer` `APPROVE` 後に `$merger` を**別 agent**として起動し、final gate を委譲する。
- `gh-pr-reviewer` または merger の `NG` を、次 cycle の maker packet または PR hygiene 作業に変換する。

`explorer` は常用しない。対象ファイルが広すぎて file mapping ができない場合だけ、補助的に使う。

詳細な packet 形式が必要なときは [references/templates.md](references/templates.md) を読む。
実際の呼び出し文面が必要なときは [references/prompt-examples.md](references/prompt-examples.md) を読む。

## Invocation Contract

最小入力は Issue 指定だけでよい。

- `Use $gh-issue-resolver on <owner/repo#number>`
- `$gh-issue-resolver を使って <Issue URL> を進めて`

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
- `merger_state_changed`: `pending`, `ng`, `approved`, `merged` のいずれかに変わった

heartbeat には少なくとも次を含める。

- current checkpoint
- branch
- worktree
- PR
- blockers
- next move
- terminal result が `in_progress` なのか `gh-pr-reviewer-gate-pending` / `merger_pending` / `ready_to_merge` / `merged` / `done` なのか

親 orchestrator が resume できるよう、曖昧な「ほぼ終わり」「PR を出したので完了」は禁止する。

親 orchestrator が `reviewed PR with merger APPROVE` を要求している場合、child はその terminal state を満たすまで lane owner の責務を持つ。権限不足、`gh-pr-reviewer` / merger 待ち、外部判断待ちのときだけ `gh-pr-reviewer-gate-pending`, `merger_pending`, `blocked` として制御を返す。

## Workflow

### 1. Issue 指定で開始する

- Issue を URL または `owner/repo#number` で正規化する。
- `gh issue view` と必要なら comment API で body / comments / labels / metadata を読む。
- 既存の `$gh-issue-reviewer` または legacy `$spacex-chief-engineer` review から、accepted scope, constraints, non-goals, blocking concerns を抽出する。
- 抽出結果を `Issue Brief` にまとめる。

`$gh-issue-reviewer` または legacy `$spacex-chief-engineer` review 済みの証拠が見つからなければ、maker loop を開始しない。その場合は「先に issue readiness review が必要」として停止する。

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
- 守るべき issue review 制約
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
同じ lane で review comment 対応と merger gate 完了まで進めるのがデフォルトである。

### 5. PR を `$gh-pr-reviewer` でレビューする

- 親セッションは `spawn_agent` などで `$gh-pr-reviewer` を**別 agent / 別 thread**として起動する。
- PR Reviewer agent には `fork_context=false` を優先し、親セッションの実装 reasoning を丸ごと渡さず、PR URL、統合後の diff, changed files, test evidence, known gaps など review に必要な最小限の packet だけを渡す。
- PR Reviewer は計画ではなく、PR 上の実装済み差分をレビューする。
- PR Reviewer は `gh-pr-reviewer` の標準フローで review を行い、`APPROVE` か `NG` を返す。
- PR Reviewer には、chat 上の判定に加えて PR 上へ gate comment を残すことを明示的に要求する。comment には literal な `$gh-pr-reviewer` と、最終行の `APPROVE` または `NG` を含めさせる。
- 曖昧な「ほぼよい」「条件付きでよい」は `NG` として扱い、再作業項目へ落とす。
- 親セッションが `gh-pr-reviewer` skill を自分でなぞっても、それは gate ではなく preflight review に留まる。**別 agent の判定が返るまで cycle は完了しない。**
- `gh-pr-reviewer` が chat では `APPROVE` を返しても、PR comment を残していなければ merger gate に進めてはいけない。

PR Reviewer への packet には次を含める。

- 元 Issue の accepted scope
- PR URL
- 既存 issue review guidance
- 今 cycle で変更した内容
- 検証結果
- 既知の未解決事項
- 今回求める gate 判定
- PR に残すべき gate comment 形式

別 agent の PR Reviewer を起動できない場合:

- 親セッションは PR 作成・evidence 整理までは進めてよい。
- ただし `APPROVE` 扱いで完了してはいけない。
- 状態は `gh-pr-reviewer gate pending` または `degraded: gh-pr-reviewer unavailable` として止める。

### 6. `gh-pr-reviewer` `APPROVE` 後に `$merger` を実行する

- 親セッションは `gh-pr-reviewer` の PR comment を確認したあと、`$merger` を**別 agent / 別 thread**として起動する。
- merger agent には PR URL と、PR Reviewer が残した gate comment が prerequisite であることを渡す。
- merger は次を確認する。
  - PR が `OPEN` で draft ではない
  - PR 上に `$gh-pr-reviewer` の `APPROVE` comment がある
  - PR の review thread がすべて resolved である
- `mergeStateStatus == CLEAN` が確認できる
- merger は条件を満たさない、または確認不能な場合、PR に merger の `NG` コメントを残して `NG` を返す。
- merger は条件を満たした場合、PR に merger の `APPROVE` コメントを残して返す。
- merger はデフォルトでは merge しない。`merge:true` が packet に明示され、かつ merger 自身が `APPROVE` した場合にだけ `gh pr merge` を実行してよい。
- 親セッションや `gh-pr-reviewer` が merger の手順を自己適用しても、それは merger gate ではない。

merger への packet には次を含める。

- PR URL
- PR Reviewer comment の期待形式
- GitHub 上の merge-ready 性も確認対象であること
- unresolved review thread は blocker であること
- merger comment の期待形式
- `merge:true | false` の指定
- 今回求める final gate 判定

別 agent merger を起動できない場合:

- 親セッションは `gh-pr-reviewer` gate 完了までは進めてよい。
- ただし完了扱いにしてはいけない。
- 状態は `merger gate pending` または `degraded: merger unavailable` として止める。

### 7. `gh-pr-reviewer` または merger が `NG` なら戻る

- `gh-pr-reviewer` / merger の `NG` を論点ごとに分解する。
- コード修正が必要な論点は、次 cycle の maker packet に落とし込む。
- review thread resolve や `gh-pr-reviewer` comment 追記のような PR hygiene だけが不足している場合は、親セッションがその不足を解消して 5 または 6 に戻ってよい。
- scope creep を防ぐため、Issue の外に広がった rework は切り離す。
- PR は閉じず、同じ PR を更新し続けることを基本とする。
- 同じ理由で 2 cycle 連続 `NG` になったら、packet の切り方か設計前提が悪い可能性が高い。親セッションが loop を止め、Issue Brief を再構成する。

### 8. merger `APPROVE` で終了する

`APPROVE` の意味は execution mode で変わる。

- `standalone`: この step の条件を満たせば完了してよい
- `orchestrated-child`: `APPROVE` は `ready_to_merge` を返すための terminal condition である。`merge:true` のときだけ `merged` を返してよい

次をすべて満たしたときだけ完了とする。

- **別 agent として起動された** `$gh-pr-reviewer` が `APPROVE` を返した。
- その PR Reviewer が、PR 上へ `$gh-pr-reviewer` 署名付きの `APPROVE` comment を残している。
- **別 agent として起動された** `$merger` が merge-ready 条件を確認し、PR 上へ `$merger` 署名付きの `APPROVE` comment を残している。
- 対応 PR が作成済みまたは最新状態に更新済みである。
- Issue の acceptance criteria が evidence 付きで満たされている。
- main regression risk と test gaps が明示されている。
- 親セッションが、Issue のどの約束をどの変更で満たしたか説明できる。

`orchestrated-child` の場合、`gh-pr-reviewer` `APPROVE` だけでは `success` と言わず、merger が未完了なら `merger_pending` を返す。merger `APPROVE` が得られたら `ready_to_merge` を返す。`merge:true` が明示され、merger が実際に merge を完了した場合だけ `merged` を返す。

## Tooling Guidance

優先するコマンド:

```bash
gh issue view <issue>
gh api repos/<owner>/<repo>/issues/<number>/comments --paginate
gh pr view <pr>
gh pr create
gh pr edit <pr>
gh pr comment <pr>
gh api graphql -f query='... reviewThreads ...'
rg --files
rg <pattern>
```

追加方針:

- 実装編集は `apply_patch` を使う。
- discovery は `rg` を優先する。
- maker が走らせる確認は、broad なフルテストより、packet に紐づく focused check を優先する。
- PR 操作は親セッションが行う。maker に PR 作成や更新を任せない。
- `$gh-pr-reviewer` review 前に、親セッションが最低限の integration check を行う。
- `gh-pr-reviewer` gate と merger gate は親セッションではなく、別 agent 起動で実行する。

## Guardrails

- acceptance criteria は Issue に定義された scope を source of truth とする。
- completion は Issue の DoD を evidence 付きで満たしたときだけ返す。
- parallel maker は ownership を分離できる packet にだけ使う。
- parent session は maker output を統合し、evidence を確認し、PR の ownership を持つ。
- PR gate は `$gh-pr-reviewer` が実コードと検証結果を見て判定する。
- merger gate は PR 上の `$gh-pr-reviewer` comment、resolved review threads、GitHub の merge-ready signal を満たしたときにだけ通す。
- merge 実行は `$merger` が `merge:true` を受けたときだけ行う。
- gate 判定は実装 agent と別 context の agent result を evidence とする。
- gate を起動できない場合は pending または degraded として返す。
- `orchestrated-child` は requested terminal state を満たしたときだけ `done`、`ready_to_merge`、`merged` を返す。
- PR 作成、`gh-pr-reviewer` `APPROVE`、heartbeat は checkpoint として扱う。
- child は requested terminal state に到達するか、明示的な blocker が出るまで lane ownership を持つ。
- この skill は Issue 起点の実装と gate 完了に使う。
