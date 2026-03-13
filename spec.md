# SPEC.md

> Canonical document note:
> この仕様書の Git 上の実ファイル名は `spec.md` だが、repo 内の canonical
> document name は `SPEC.md` とする。case-insensitive filesystem では
> `SPEC.md` と legacy `spec.md` の path が衝突しうるため、canonical docs
> と current issues で `SPEC.md` と書かれている場合は、このファイルを指す。

## 1. Purpose

本仕様書は `comic_crawler` の受け入れ仕様を定義する。
本仕様書は、外部から観測可能な契約、および受け入れ判定に必要な条件を定義することを目的とする。
内部実装方式、実装分割、最適化方式、再試行アルゴリズムの詳細は本仕様書の主対象ではない。

本仕様書で特に重視する観点は以下とする。

- state 安全性
- Discord 上の可読性
- 同一話の再通知防止
- 障害時の可視化
- delivery failure 後の再送可能性
- 自動テストによる受け入れ判定可能性

---

## 2. Scope

本仕様の対象は以下とする。

- watchlist v2 / state v2 を前提とした runtime の外部契約
- Discord `latest` query
- Discord `fetch` trigger
- Daily notification
- run report
- state 安全性保証
- 通知重複防止保証
- delivery / recovery の外部契約
- セキュリティ要件
- 性能目標
- 受け入れ試験条件

---

## 3. Non-scope

本仕様の対象外は以下とする。

- Status CLI の受け入れ仕様
- Backlog CLI の受け入れ仕様
- retry / backoff の具体アルゴリズム
- CLI 文面の細部固定
- `fetch` の完全排他
- metadata 改善誤通知の高度な改善
- 内部設計品質そのものの評価
- 将来の source 追加や大規模機能拡張

---

## 4. Runtime assumptions

- runtime が正とする永続データは watchlist v2 / state v2 のみとする
- runtime baseline は Python 3.12 系とする
- Discord surface は `latest`、`fetch`、Daily notification、run report を持つ
- 本仕様は受け入れ担当が観測可能な挙動を優先する
- 主要受け入れ条件はモックベース自動試験で判定する
- Discord 実機検証は補助的な検証として扱う

---

## 5. Glossary

- **watchlist v2**: runtime が正とする監視対象一覧
- **state v2**: runtime が正とする永続状態
- **latest query**: 保存済み state を参照する read-only 問い合わせ
- **fetch trigger**: Discord から 1 回の run を起動する write path の問い合わせ
- **daily notification**: 更新があったときに送られる Discord 通知
- **run report**: 各 run ごとに送られる実行結果通知
- **work_id**: 作品単位で不変の識別子
- **latest_key**: 更新検知と通知重複防止の比較キー

---

## 6. Discord interface

### 6.1 Initial acknowledgment

- Discord inbound command は、初期応答と本応答の 2 段階で扱ってよい
- 初期応答として、認識した元メッセージにチェックマークのスタンプ送信を試行してよい
- スタンプ送信の試行は command ごとの本処理開始前に行ってよい
- スタンプ送信は受領確認のための best-effort とし、送信保証や再試行を要求しない
- スタンプ送信失敗は command 本処理の失敗理由にしてはならない
- スタンプ送信結果待ちによって command 本処理を不必要に遅延させてはならない

### 6.2 Discord `latest` query

#### 6.2.1 Input contract

- trim 後に本文がちょうど `latest` であるメッセージを `latest` query と解釈する
- `latest` query は read-only である
- `latest` query は live crawl を起動してはならない
- `latest` query は watchlist/state を変更してはならない
- `latest` query 実行失敗は、定期 run や `fetch` run の契約に影響してはならない

#### 6.2.2 Source of truth and ordering

- source of truth は watchlist v2 + state v2 とする
- 一覧順は watchlist の入力順を正とする
- `enabled=false` の作品は既定では一覧に含めない
- watchlist に存在しない orphaned state entry は一覧に含めない
- 各行は該当作品の保存済み最新状態から生成する
- 全体の最終巡回表示は保存済み run 時刻から生成する

#### 6.2.3 Response contract

正常系の本文は、以下の意味構造を持たなければならない。

1. これは保存済みの最新話一覧であること
2. 最終巡回時刻
3. 現在の一覧本体

本文の構造例:

```text
保存済みの最新話一覧です
最終巡回: 2026-03-07 17:03:09 JST
現在のリスト:
[第71話](<https://example.com/episodes/71>)　作品A
[第8話](<https://example.com/episodes/8>)　作品B
```

以下を契約とする。

- 1 行目は保存済み一覧であることを示す固定表現とする
- 最終巡回時刻は保存済み run 時刻を TZ 基準のローカル時刻で表す
- 最終巡回時刻が無い場合は、未実行であることが分かる表現を使う
- 3 行目は一覧開始を示す固定表現とする
- 各作品は 1 行で返す
- 各行は少なくとも「最新話ラベル」「作品名」を含む
- URL がある場合は Discord Markdown link 形式を用いる
- URL が無い場合は plain text で成立する
- latest 未取得作品は未取得であることが分かる表現にする

#### 6.2.4 Label fallback rules

作品名は、以下の優先順で選ぶ。

1. `latest.series_title`
2. `latest.series`
3. `work_id`

最新話ラベルは、以下の優先順で選ぶ。

1. `latest.episode_title`
2. `latest.episode_code`
3. `latest.url`
4. 未取得相当の固定表現

URL が存在し、`episode_title` が無い場合でも、link label には `episode_code` を優先してよい。
`episode_title` と `episode_code` が無いときのみ URL 自体を label にしてよい。

#### 6.2.5 Episode label truncation rules

latest query の一覧は、携帯端末で縦に比較しやすいことを優先する。
そのため、長い最新話ラベルは省略してよい。

省略ルールは以下とする。

- 省略対象は、話数ヘッダの後ろに続く subtitle を主対象とする
- 話数ヘッダ自体は可能な限り保持する
- 話数ヘッダと subtitle を分離できる場合は、subtitle のみに truncate を適用する
- subtitle の最大長は `…` を含めて 8 文字とする
- 8 文字を超える場合は、先頭 7 文字を残して `…` を付ける
- 省略記号は常に `…` とする
- 分離できない場合のみ、ラベル全体に fallback truncate を適用する
- fallback truncate の最大長は `…` を含めて 20 文字とする
- 20 文字を超える場合は、先頭 19 文字を残して `…` を付ける
- 構造判定上は Unicode を前提とし、全角/半角差でルールを分けない

例:

- `第71話 abcdefghijk` → `第71話 abcdefg…`
- `第71話 あいうえおかきくけ` → `第71話 あいうえおかき…`
- `abcdefghijklmnopqrstu` → `abcdefghijklmnopqrs…`
- `第55話後編` → `第55話後編`

#### 6.2.6 Empty / stale / partial-failure semantics

一覧対象作品が 0 件、または全作品が未取得の場合は、保存済み結果がまだ無いことを示す本文を返す。

例:

```text
保存済みの最新話一覧です
最終巡回: まだ実行されていません
現在のリスト:
- まだ保存済みの監視結果がありません
```

また、以下を契約とする。

- `latest` query は「更新なし」を意味しない
- `latest` query はあくまで保存済み state の参照である
- 一部作品に直近 failure がある場合、保存済みデータであることを示す warning を末尾に加えてよい
- stale や failure を理由に live crawl を自動起動してはならない
- source failure と run-level failure は「更新なし」と混同される文言で返してはならない

---

### 6.3 Discord `fetch` trigger

#### 6.3.1 Input contract

- trim 後に本文がちょうど `fetch` であるメッセージを fetch trigger と解釈する
- fetch trigger は write path である
- fetch trigger はその時点で 1 回の run を開始するための手動トリガーである

#### 6.3.2 Execution contract

- `fetch` で開始された run は、定期 run と同じ更新検知・state 更新・Daily notification・run report 契約に従う
- `fetch` と定期 run の違いは trigger source のみとする
- `fetch` 同時実行は受け入れ上は許容する
- ただし、同時実行が起きても state 破損は許容しない

#### 6.3.3 Response contract

- `fetch` の初期応答は本文返信ではなく 6.1 のチェックマークスタンプで表現してよい
- 利用者は Daily notification または run report で結果確認すべきであることを理解できること
- `fetch` の結果確認は主として後続通知 surface に委ねてよい

---

### 6.4 Daily notification

#### 6.4.1 Send condition

- 更新があった run のみ送る
- 更新 0 件の run では送らない
- 通知対象は、その run で `latest_key` が変化した作品のみとする
- metadata の改善のみは通知対象にしない
- 更新通知の並び順は watchlist 順を正とする

#### 6.4.2 Deduplication contract

- 同一話の再通知防止は `work_id + latest_key` を基準とする
- 同じ `work_id + latest_key` の組み合わせに対する Daily notification は重複送信してはならない
- `fetch`、定期 run、再送処理のいずれにおいても同じ基準を適用する

#### 6.4.3 Response contract

更新通知本文は、以下の意味構造を持たなければならない。

1. 新着エピソードを検知したこと
2. その run が属するローカル日付
3. 各更新の新旧比較一覧

本文の構造例:

```text
新着エピソードを検知しました（2026-03-02）
[蜘蛛ですが、なにか？：第78話その1](<https://example.com/new>)←第77話その2
[航宙軍士官、冒険者になる：第62話①](<https://example.com/new2>)←第61話
```

以下を契約とする。

- 1 行目は新着検知を示す固定表現とする
- 日付は通知生成時刻ではなく、その run が属するローカル日付を使う
- 2 行目以降は 1 更新につき 1 行とする
- 各行は少なくとも「作品名」「新しい最新話」「前回話」を含む
- 作品名と新しい最新話の区切りは全角コロン `：` を使う
- 新旧比較の区切りは固定で `←` を使う
- URL がある場合は Discord Markdown link 形式を使う
- URL が無い場合は plain text に degrade してよい

#### 6.4.4 Label fallback rules

作品名は、以下の優先順で選ぶ。

1. `to.series_title`
2. `to.seriesTitle`
3. `to.series`
4. `id`

新しい最新話は、以下の優先順で選ぶ。

1. `to.episode_title`
2. `to.episodeTitle`
3. `to.episode_code`
4. `to.episodeCode`
5. `to.url`

前回話は、以下の優先順で選ぶ。

1. `from.episode_title`
2. `from.episodeTitle`
3. `from.episode_code`
4. `from.episodeCode`
5. `from.url`
6. 未取得相当の固定表現

#### 6.4.5 Notification label normalization

- 新しい最新話には latest query と同じ truncate ルールを適用してよい
- 前回話にも同じ truncate ルールを適用してよい
- 作品名は原則として truncate しない
- 作品名の極端な長さに対する別ルールは本仕様の対象外とする

---

### 6.5 Run report

#### 6.5.1 Send condition

- run report は更新有無にかかわらず毎 run 送る

#### 6.5.2 Meaning contract

run report は少なくとも、以下を区別可能でなければならない。

- 更新がなかった
- run が失敗した
- 更新はあったが delivery に失敗した

#### 6.5.3 Minimum contents

run report は少なくとも以下を含まなければならない。

- 実行時刻
- trigger source
- 更新検知件数
- Daily notification を送信したか
- source failure / run-level failure の要約
- 現在状態または最新状態の要約

#### 6.5.4 Format policy

- run report の文面細部は固定しない
- 受け入れ判定では意味が伝わることを重視する
- 更新 0 件と failure が混同されないことを優先する

---

## 7. State safety guarantees

### 7.1 JSON integrity

- 異常終了しても state は JSON として壊れてはならない
- broken JSON 状態を runtime の正状態として残してはならない

### 7.2 Reader visibility

- 同時実行が起きても reader が読めない状態を作ってはならない
- reader は保存途中の中間状態を観測してはならない
- reader からは旧 state または新 state のいずれかとして読めることを保証対象とする

### 7.3 Acceptance impact

- state 破損は受け入れ NG とする
- state 安全性の実現方式は本仕様の対象外とし、設計書で定義する

---

## 8. Notification deduplication guarantees

- 通知重複防止の基準は `work_id + latest_key` とする
- `latest_key` が不変で、タイトルや補足情報のみが改善された場合は通知してはならない
- 同一話の再通知防止は Daily notification の必須受け入れ条件とする

---

## 9. Delivery and recovery guarantees

- delivery failure は更新なしと混同されてはならない
- 通知 delivery は再送可能でなければならない
- Discord 応答不能や delivery failure が起きても、再試行可能な状態を保持できなければならない
- partial success が起きうることを前提とし、同一 event は stable id により再利用できること
- retry / backoff の具体方式は本仕様の対象外とする

---

## 10. Security requirements

- token をログに出してはならない
- webhook URL をログに出してはならない
- token / webhook URL を run report に出してはならない
- エラー出力にも秘匿情報を含めてはならない

---

## 11. Performance targets

- watchlist 100 件で 30 秒以内を目標とする
- Discord 初期応答は latest / fetch ともに 3 秒以内を目標とする
- latest の本応答は 10 秒以内を目標とする
- fetch の完了は watchlist 100 件で 30 秒以内目標に準拠する
- 本章の値は目標値であり、現時点では必達条件ではない

---

## 12. Acceptance tests

### 12.1 General policy

- 主要受け入れ条件は自動テストで判定可能でなければならない
- 受け入れ主判定はモックベース自動試験とする
- Discord 実機確認は補助的な検証として自動化可能であることが望ましい
- 実機確認は主受け入れ判定ではなく、回帰検知または smoke に位置づける

### 12.2 `latest`

自動テストで少なくとも以下を検証する。

- `latest` が read-only であり live crawl を起動しないこと
- 認識した `latest` message に対して、本文応答前にチェックマークの初期応答スタンプ送信を試行できること
- 初期応答スタンプ送信の失敗が `latest` 本文応答の失敗や不要な遅延を起こさないこと
- `latest` が watchlist 順で返ること
- orphaned state entry を表示しないこと
- `enabled=false` の作品を既定で表示しないこと
- 未取得作品を未取得として表現すること
- URL 有無に応じて link / plain text が切り替わること
- fallback ルールが守られること
- truncate ルールが守られること
- stale / partial failure 時も live crawl を起動しないこと
- 生成文字列が構造・情報順・表記ルールを満たすこと

### 12.3 Daily notification

自動テストで少なくとも以下を検証する。

- 更新あり run のみ送信すること
- 更新 0 件 run では送信しないこと
- 送信対象が `latest_key` 変化作品のみであること
- `work_id + latest_key` 基準で重複送信しないこと
- metadata 改善のみでは送信しないこと
- 複数更新が watchlist 順で並ぶこと
- URL 有無で表現が degrade すること
- fallback ルールが守られること
- truncate ルールが守られること
- 生成文字列が構造・情報順・表記ルールを満たすこと

### 12.4 `fetch`

自動テストで少なくとも以下を検証する。

- `fetch` が write path として run を起動すること
- 認識した `fetch` message に対して、run 起動前にチェックマークの初期応答スタンプ送信を試行できること
- `fetch` の初期応答を本文返信なしでスタンプのみへ委ねられること
- 初期応答スタンプ送信の失敗が `fetch` run 起動の失敗や不要な遅延を起こさないこと
- trigger source 以外の契約が定期 run と整合すること
- 同時実行時にも state が JSON として壊れないこと
- 同時実行時にも reader が読めない状態を作らないこと

### 12.5 Run report

自動テストで少なくとも以下を検証する。

- 毎 run 送信されること
- 更新なしと failure が区別できること
- delivery failure が更新なしと区別できること
- 最低限の意味要素が読み取れること

### 12.6 Delivery and recovery

自動テストで少なくとも以下を検証する。

- delivery failure が更新なし扱いされないこと
- 再送可能状態が保持されること
- 再送成功後に保留状態が解消できること
- same event の stable id が維持されること

### 12.7 State safety

自動テストで少なくとも以下を検証する。

- state 保存途中での異常終了後も JSON として読めること
- 書き込み中の並行 reader が parse error を起こさないこと
- 高頻度並列実行でも state 破損を起こさないこと

### 12.8 Security

自動テストで少なくとも以下を検証する。

- token がログ / report / error に露出しないこと
- webhook URL がログ / report / error に露出しないこと
- failure 時にも秘匿情報が露出しないこと

### 12.9 Performance

性能は benchmark / target として扱う。
少なくとも以下を継続測定できることが望ましい。

- watchlist 100 件での run 所要時間
- latest 初期応答時間
- fetch 初期応答時間
- latest 本応答時間

---

## 13. Out of acceptance scope

以下は本受け入れ仕様の主対象外とする。

- 内部設計の美しさや抽象度
- 実装の分割方法そのもの
- retry/backoff の数式や細部
- CLI 出力の細かな文言
- Status CLI / Backlog CLI の詳細契約
