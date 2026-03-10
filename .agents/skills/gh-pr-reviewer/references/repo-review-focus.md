# de-group Review Focus

必要なときだけこのファイルを読む。
この repo で `gh-pr-reviewer` が見るべき「固定チェックリストではない PR Reviewer の観点」をまとめる。

## 1. Repo Fit

この repo は dotfiles、skill、agent 設定、文書が同居しており、変更ごとに重視すべき観点が少しずつ違う。
したがって PR Reviewer は「より大きくて抽象的な設計が美しいか」ではなく、「この変更量でこの repo の実際の構成に素直に収まるか」を見る。

見ること:
- 小さな変更で済むところに大きな構造を持ち込んでいないか
- 変更の重さが目的に見合っているか
- 実装後の保守負荷が無駄に増えていないか

## 2. Outcome Fit

PR Description や関連 Issue の約束が、実装の結果として本当に達成されているかを見る。

見ること:
- 実装が promise を満たしているか
- 実装の意図が差分から読めるか
- 仕様を満たしたように見えて、別の振る舞いを壊していないか

## 3. Resolution Quality

過去の chief-engineer 指摘は「コメントに返事したか」ではなく、「実装または文書として納得できる形で解消したか」を見る。
レビューで `NG` を出すなら、解消の方向を一段具体化して返す。

見ること:
- 指摘への対処が局所的な回避で終わっていないか
- 修正によって別の無理が生まれていないか
- blocker を隠すために説明や docs で濁していないか

## 4. Validation Fit

PR Reviewer は「十分に証明されたか」を見る。ここでの十分さは、変更のリスクに比例する。

見ること:
- 軽微な変更なら軽い根拠で足りるか
- skill / agent / 運用導線の変更なら、それに見合う根拠があるか
- 根拠が無いのに楽観的に approve していないか

## 5. Approval Bar

`APPROVE` を出してよいのは、以下が揃うときだけ。

- base review に blocker がない
- repo fit に無理がない
- PR Description と実装のズレが説明可能
- 過去 chief-engineer comment の未解消 blocker がない
- evidence が十分、または少なくとも blocker を否定できる一次根拠がある

`NG` を出すなら、以下も満たすこと。

- blocker が実際に merge-ready 性を下げる理由を説明できる
- approve に近づく代替案または修正の方向を示せる
