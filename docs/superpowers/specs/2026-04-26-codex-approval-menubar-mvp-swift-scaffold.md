# Codex Approval Menubar Swift Scaffold

**Date:** 2026-04-26  
**Repository:** `kentoku24/comic_crawler`  
**Status:** Draft scaffold

---

## What this commit adds

`apps/codex_approval_menubar/` に SwiftUI menubar app の最小骨格を追加する。

### Included

- `Package.swift`
- `MenuBarExtra` ベースのアプリ起動点
- approval assessment API client
- in-memory store
- sample approval requests
- latest assessment / history 表示
- high-risk / medium-risk request 時のローカル通知

### Not included yet

- Codex の実 approval event 監視
- background bridge daemon
- request history persistence
- approve / deny を Codex へ返す導線
- signed distribution / notarization

## Why scaffold first

いきなり実イベント監視まで入れると、Codex 側の event source の不確定さで実装が濁る。  
そのため今回は、**backend contract を叩ける menubar surface** を先に固定する。

## Proposed next slice

次の実装単位は次のどちらか。

### Option A: local bridge

- Codex approval event を local webhook / stdin / log watch で受ける
- bridge process が menubar app に転送する
- app は API assessment 結果を表示する

### Option B: embedded assessment fallback

- backend 未接続時だけ Swift 側の非常用ルールを使う
- ただし source of truth が二重化するので非推奨

推奨は **Option A**。

## Directory shape

```text
apps/
  codex_approval_menubar/
    Package.swift
    README.md
    Sources/
      CodexApprovalMenubar/
        main.swift
        Models.swift
        ApprovalStore.swift
        ApprovalAPIClient.swift
        SampleApproval.swift
        Views.swift
```

## Build assumptions

- macOS 14+
- Swift 5.10+
- `MenuBarExtra` を使うため SwiftUI App lifecycle を前提

## Recommendation summary

この段階では十分正しい。  
「Codex からのイベント取得」はまだ未解決だが、**表示面と API 接続面を先に成立**させたことで、残りの work は bridge のみに集中できる。
