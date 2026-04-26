# Codex Approval Helper MVP

**Date:** 2026-04-26  
**Repository:** `kentoku24/comic_crawler`  
**Status:** Draft MVP / implementation scaffold

---

## Goal

Codex がユーザー承認を要求した瞬間に通知し、**その内容を許可してよいか判断するための短い材料**を返す仕組みを作る。  
最終形は Mac のメニューバーアプリだが、最初に作るべき source of truth は UI ではなく **approval assessment contract** である。

## Why this order

メニューバーアプリから先に作ると、判定ロジックが UI 内に埋まりやすい。  
この repo はすでに operations-first で machine-facing API を育てる方針なので、まず Python 側に次を置く。

1. Codex approval request の入力 schema
2. ルールベースの risk assessment
3. machine-facing JSON API
4. 後から Mac app が叩ける安定インターフェース

これにより、Swift 側は「イベント取得 + 通知 + 詳細表示」に集中できる。

## Product shape

### User story

- Codex が「このコマンドを実行してよいか」と承認を求める
- Mac メニューバーアプリがそれを検知する
- アプリは assessment API に command / cwd / justification を送る
- ユーザーは次をひと目で見る
  - 何をしようとしているか
  - どの種類のリスクか
  - 許可してよさそうか
  - どこを確認すべきか

### Non-goals for MVP

- Codex 本体への approve / deny 自動送信
- LLM による高度な意図推定
- 完全な shell parser
- すべての危険コマンドの厳密判定
- macOS ネイティブアプリの完成

## MVP architecture

```text
Codex approval event
  -> menu bar app / bridge process
    -> POST /api/codex/approval-assess/
      -> web_admin.operations.codex_approvals
        -> rule-based assessment
      <- JSON assessment
    -> local notification / menu bar detail panel
```

## Input contract

```json
{
  "command": "git push origin main",
  "working_directory": "/Users/ken/project",
  "source": "codex-cli",
  "justification": "Push the completed fix to remote"
}
```

### Required fields

- `command`

### Optional fields

- `working_directory`
- `source`
- `justification`

## Output contract

```json
{
  "ok": true,
  "assessment": {
    "summary": "risk=medium; categories=write, network; command=git push origin main",
    "recommendation": "inspect_before_allow",
    "risk_level": "medium",
    "requires_human_attention": true,
    "categories": ["write", "network"],
    "reasons": [
      "ファイル変更または外部状態変更の可能性がある: `git push`",
      "ネットワーク通信を伴う可能性がある: `git push`"
    ],
    "allow_reasons": [
      "Codex 側の説明: Push the completed fix to remote"
    ],
    "deny_reasons": [
      "ファイル・git・infra の状態を変更する可能性がある",
      "外部送信やリモート変更が起きうる"
    ],
    "command": "git push origin main",
    "working_directory": "/Users/ken/project",
    "source": "codex-cli"
  }
}
```

## Recommendation levels

- `likely_allow`
  - 低リスクの読み取り中心
- `inspect_before_allow`
  - 副作用はあるが、文脈が妥当なら許可しうる
- `deny_or_inspect`
  - 破壊的 / 秘密情報 / 権限昇格を含み、追加確認なしで許可すべきでない

## Rule set in MVP

### Category detection

- `read_only`
- `write`
- `network`
- `privilege`
- `secret`
- `destructive`
- `compound`
- `unknown`

### Current heuristic examples

- `cat`, `ls`, `grep`, `git diff` -> `read_only`
- `rm`, `chmod`, `git commit`, `docker`, `kubectl`, `gcloud` -> `write`
- `curl`, `wget`, `scp`, `git push` -> `network`
- `sudo`, `su`, `doas` -> `privilege`
- `.env`, `id_rsa`, `token`, `password` -> `secret`
- `rm -rf`, `mkfs`, `dd`, `drop table` -> `destructive`
- `&&`, `||`, `|`, `;` を含む -> `compound`

## Why this belongs in comic_crawler

この repo はすでに machine-facing API と operations-first の運用基盤を持つ。  
そのため、approval helper の核心を **運用 API の一部** として育てるのは自然。  
将来的に別 repo へ切り出すとしても、先に contract を固める価値がある。

## Next steps

### Step 1: now

- `web_admin.operations.codex_approvals` を追加
- `/api/codex/approval-assess/` を追加
- OpenAPI に endpoint を露出
- ルールベースの MVP 判定を返す

### Step 2: next

- fixture ベースのテスト追加
- command ごとの reason 文面を改善
- shell tokenization を少し厳密化
- allow/deny recommendation の calibration

### Step 3: later

- SwiftUI `MenuBarExtra` アプリ
- local bridge で Codex approval event を監視
- assessment API へ転送
- macOS notification / menu detail / history 表示

## Swift app recommendation

Mac 側は次の構成を推奨する。

- SwiftUI + `MenuBarExtra`
- approval event watcher
  - まずは log tail / JSON stdin / local webhook のどれか
- network client
  - `POST /api/codex/approval-assess/`
- notification presenter
- latest requests list + detail pane

### Do not do first

- いきなり TCC 深掘りや Accessibility hook に突っ込む
- 判定ロジックを Swift 側へ複製する
- approve/deny 自動化から始める

## Open questions

- Codex approval event の最良の取得元は何か
  - structured log
  - local webhook
  - stdout interceptor
  - approval prompt file
- approve/deny 導線を Mac アプリから返すべきか
- assessment API をローカルで持つか、Cloud Run で持つか

## Recommendation summary

おすすめは、**先に backend contract を作り、その後に menu bar app を薄く乗せる** こと。  
今回の実装はその第一歩として十分筋が良い。Swift アプリは次のコミットで切ればいい。
