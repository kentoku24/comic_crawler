# comic_crawler Issue Review Focus

必要なときだけこのファイルを読む。
この repo で `chief-issue-reviewer` が見るべき issue readiness の観点をまとめる。

## 1. Repo Fit

この repo は単一の crawler runtime と周辺 docs が中心で、巨大な orchestration layer を前提にしていない。
issue review でも「きれいな抽象化」より「この repo に素直に収まるか」を優先する。

見ること:

- 小さい問題に大きすぎる構造を要求していないか
- 実装の重さが目的に見合っているか
- issue 自体が unnecessary refactor を誘発していないか

## 2. Contract Fit

comic_crawler は watchlist/state/schema/notification/report などの contract が挙動を決める。
issue が implement-ready かどうかは、critical contract が着手前に固定されているかで決まる。

見ること:

- process model が明記されているか
- state mutation / read-only の境界が明記されているか
- failure semantics が `更新なし` と混同されないか
- dedupe / ordering / source of truth が明記されているか

## 3. Validation Fit

この repo は Python のユニットテスト群で contract を守る形が多い。
したがって issue も「何をテストで固定すべきか」が弱いと implement-ready ではない。

見ること:

- テストすべき分岐が明記されているか
- failure path がテスト対象に含まれているか
- DoD が人間の感想でなく testable か

## 4. Approval Bar

`APPROVE` を出してよいのは、次が揃うときだけ。

- implementer が architecture-critical な判断を推測しなくてよい
- 必須テストの観点が issue に固定されている
- scope と non-goals が衝突していない
- repo の規模に対して無理のない設計である

`NG` を出すなら、approve に近づく最短の改善案を返す。

