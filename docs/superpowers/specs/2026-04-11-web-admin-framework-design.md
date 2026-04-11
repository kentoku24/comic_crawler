# Web Admin Framework Design

**Date:** 2026-04-11
**Repository:** `kentoku24/comic_crawler`
**Status:** Proposed

---

## Goal

このリポジトリに、自分用の管理画面を無理なく追加できる Web 基盤を決める。  
初期フェーズでは watchlist / state / health / manual run を扱う internal admin を最短で立ち上げ、将来的には認証強化、複数ユーザー対応、課金 UI の追加まで見据えても破綻しない構成にする。

## Current State

### Existing runtime

- runtime の主軸は Python 3.12
- crawler / state / storage / notifier は `manga_watch/` 以下に実装済み
- deploy target は GCP Cloud Run Job / Cloud Run Service
- CLI / Discord / scheduled run が既存の操作面になっている

### Existing strengths

- 監視対象や state 更新のドメインロジックはすでに Python に集約されている
- source adapter, runner, storage abstraction, Discord surface は既に動いている
- README と canonical docs が Python / GCP 運用を前提に整理されている

### Current gaps

- watchlist や unread 状態をブラウザから確認・更新できない
- manual run や health 確認が CLI / GCP / Discord に分散している
- 将来ユーザー向け UI を足すとしても、Web 層の責務分離がまだ存在しない

## Decision

Web インターフェースの第一候補として **Django** を採用する。  
初期構成は **Django + server-side rendering + 必要最小限の JavaScript** とし、internal admin を最優先で構築する。

## Why Django

### 1. Repo fit

- 現行 repo は Python 中心であり、追加ランタイムなしで自然に統合できる
- crawler 本体を別言語 stack に移し替える必要がない
- Cloud Run 上での運用パスもすでに取りやすい

### 2. Long-term maintainability

- 標準の auth, session, permission, admin が揃っている
- internal admin を短距離で作りつつ、将来の role 分離や user management に伸ばしやすい
- forms, ORM, template, middleware, management command など、運用画面に必要な基礎機能が一通り揃っている

### 3. Future billing path

- 課金 UI は Django 単体で全部自作するのではなく、Stripe Checkout / Customer Portal を組み合わせればよい
- これにより billing のコアは外部に任せつつ、アプリ側は plan gating と entitlement 表示に集中できる

## Rejected Alternatives

### Option A: Next.js App Router

長期的に public-facing SaaS frontend を強く作るなら有力だが、初期の internal admin には過剰。  
現時点で Node.js / TypeScript ランタイム、認証基盤、API 境界を新設すると、repo fit より構成複雑化のコストが先に来る。

### Option B: FastAPI + separate React frontend

API と UI の分離は明快だが、internal admin の立ち上がりとしては境界が多すぎる。  
今の段階では「きれいな分離」より「少ない構成要素で早く価値を出す」ことを優先する。

### Option C: Flask / lightweight server

最初の画面だけなら軽いが、認証・権限・管理 UI・長期保守の観点では Django より追加実装が増える。  
今回の要件では「軽さ」より「将来機能込みでの基盤完成度」を優先する。

## Non-Goals

- 最初から public SaaS 向け polished frontend を作ること
- いきなり SPA / BFF / microservices に分割すること
- crawler のドメインロジックを Django app へ全面移植すること
- billing provider をこの段階で実装確定すること
- Discord や GCP 運用導線をすぐに置き換えること

## Functional Requirements For Phase 1

Phase 1 の internal admin は最低限次を扱えるべき。

1. watchlist の一覧表示
2. work ごとの enabled 状態、source、seed URL、notification policy の確認
3. watchlist への追加、編集、無効化
4. state の latest / unread / health の閲覧
5. 手動 run の起動
6. 最近の run 結果と source error の確認
7. 自分以外に公開しない前提のログイン保護

## Proposed Architecture

### High-level shape

`manga_watch` をドメイン層として温存し、その上に Django の Web 層を追加する。  
Django app は crawler 本体を直接抱え込まず、薄い application service layer を経由して既存ロジックを呼び出す。

```text
Browser
  -> Django views / templates / forms
    -> web application services
      -> manga_watch domain modules
        -> storage / runner / notifier / source adapters
```

## Key design rule

**Django は HTTP と UI に集中し、`manga_watch` は監視ドメインの source of truth のまま保つ。**

これにより、将来 Discord, CLI, scheduler, API, Web の各 surface が増えても、監視ロジックの重複を避けやすい。

## Project Structure

初期案として、repo 直下に Django project 用ディレクトリを追加する。

```text
web_admin/
  manage.py
  project/
    settings.py
    urls.py
    wsgi.py
    asgi.py
  dashboard/
    views.py
    urls.py
    forms.py
    services.py
    templates/dashboard/
  operations/
    views.py
    urls.py
    services.py
  shared/
    auth.py
    navigation.py
```

### Responsibility split

- `manga_watch/`: crawler / state / storage / domain behavior
- `web_admin/dashboard/`: watchlist, state, health の閲覧 UI
- `web_admin/operations/`: manual run, replay, maintenance 操作
- `services.py`: Django view から domain 呼び出しを隔離する application service 層

## UI Strategy

### Rendering model

- 基本は Django template による SSR
- filter, inline toggle, confirmation modal など、小さい振る舞いだけ軽い JS を足す
- 初期段階では frontend build pipeline を前提にしない

### Why

- internal admin では first-load speed や SEO より、運用の明快さと保守性が重要
- JS build stack を早期導入しなくてよい
- HTML form と server-side validation だけで十分に成立する画面が多い

## Authentication Strategy

### Phase 1

- Django 標準 auth を利用する
- 最初は単一管理者アカウントを前提にする
- app 全体を login required にする
- destructive action は CSRF 保護と POST 限定を徹底する

### Phase 2+

- Django groups / permissions で operator, admin のような role を分ける
- Google Workspace / OAuth / SSO が必要になれば、その時点で social login を追加する

## Billing Strategy

課金が必要になったときは、Web 基盤自体を作り直さず次の拡張で対応する。

### Recommendation

- subscription signup: Stripe Checkout
- self-serve management: Stripe Customer Portal
- app side: subscription status, entitlement, plan gating の保持

### App responsibility

- 現在の plan を表示する
- entitlement に基づいて機能を開閉する
- webhook で subscription 状態を同期する

### Non-responsibility

- カード入力 UI や請求書 UI を自前実装しない

## Deployment Strategy

### Initial deployment model

- Django Web は既存 runtime と同じく Cloud Run Service に載せる前提で設計する
- crawler job とは別 service として分離する
- 初期実装では browser-facing admin 専用の新しい Cloud Run Service を作る

### Recommendation

初期実装では **別 Cloud Run Service** を採用する。  
理由は、Discord interaction endpoint と browser-facing admin では request profile, auth, rollout cadence が異なるため。  
service 名は implementation で確定するが、`comic-crawler-web` のように役割が明確な名前を推奨する。

## Data Access Strategy

Web admin は storage backend の source of truth を尊重する。

### Rules

- watchlist / state は既存 storage abstraction を通じて読む
- Web 用に別 schema を先に作らない
- storage backend が file / Firestore のどちらでも動くようにする

### Consequence

Web 導入のために crawler state model を二重管理しない。  
将来 multi-user metadata が必要になった場合だけ、Django 側 DB テーブルを追加する。

## Testing Strategy

### Phase 1 tests

- Django view / form / auth の unit tests
- application service 層の integration tests
- existing `manga_watch` contract を壊していないことの regression tests

### Priorities

1. 権限なしアクセスが拒否されること
2. watchlist 編集が既存 contract を壊さないこと
3. manual run 導線が誤って複数回同時実行されないこと
4. storage backend 差異で UI が壊れないこと

## Migration Path

### Milestone 1

- Django project scaffold
- login
- dashboard home
- read-only watchlist / state / health

### Milestone 2

- watchlist CRUD
- manual run trigger
- recent run result view

### Milestone 3

- role split
- audit trail
- safer operations UX

### Milestone 4

- subscription model
- Stripe integration
- plan gating

## Risks

### Risk 1: Tight coupling between Django and crawler internals

view から既存 module を直接つまみ始めると、Web が domain internals に密結合になる。  
これを避けるため、application service 層を最初から設ける。

### Risk 2: Web edits bypass existing validation rules

CLI / Discord と別経路で watchlist を更新すると contract drift が起きうる。  
Web も既存 validation / normalization を共通利用する必要がある。

### Risk 3: Overbuilding for a future SaaS that does not exist yet

初期段階で public SaaS 前提の複雑な frontend stack を入れると、運用価値より維持コストが先に増える。  
そのため Phase 1 は internal admin に必要な範囲へ絞る。

## Recommendation Summary

この repo の Web 基盤は、まず **Django を別 web service として追加**するのが最も現実的である。  
`manga_watch` をドメイン層として保持しつつ、Django は auth, UI, form, operation surface を担当する。  
将来のユーザー認証強化や課金導入も、この構成の上に段階的に積み上げる。

## Sources

- Django admin docs: <https://docs.djangoproject.com/en/stable/ref/contrib/admin/>
- Django auth docs: <https://docs.djangoproject.com/en/6.0/topics/auth/>
- Django release process: <https://docs.djangoproject.com/en/6.0/internals/release-process/>
- Cloud Run Django guide: <https://cloud.google.com/python/django/run>
- Next.js App Router docs: <https://nextjs.org/docs/app>
- Next.js authentication docs: <https://nextjs.org/docs/app/building-your-application/authentication>
- Stripe subscriptions overview: <https://docs.stripe.com/billing/subscriptions/overview>
- Stripe Checkout subscriptions: <https://docs.stripe.com/payments/checkout/build-subscriptions>
