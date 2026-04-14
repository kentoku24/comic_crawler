# Web Admin Framework Design

**Date:** 2026-04-11
**Repository:** `kentoku24/comic_crawler`
**Status:** Proposed

---

## Goal

このリポジトリに、自分用の管理画面を無理なく追加できる Web 基盤を決める。  
初期フェーズでは watchlist / state / health / manual run を扱う internal admin を立ち上げるが、同時に LLM や内部ツールからも同じ操作を安全に呼べる machine-facing interface を最初から定義する。  
browser UI は重要な surface だが primary interface ではなく、監視運用の source of truth になる operations contract の上に載る薄い human surface とする。

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
- LLM や内部ツールが安定して呼べる typed machine-facing contract がない
- 将来 UI を足すとしても、Web 層の責務分離がまだ存在しない

## Decision

Web 基盤は **operations-first** で設計する。  
具体的には、まず Python 内に typed command/query の application operations layer を定義し、それを machine-facing JSON/OpenAPI surface と human-facing Django UI の両方から利用する。  
human UI のフレームワークとしては **Django** を採用するが、Django は primary interface ではなく operations contract を消費する thin surface として扱う。

## Why This Shape

### 1. Outcome fit

- このプロジェクトは browser UI だけでなく LLM / tool client からも安全に操作できる必要がある
- 先に operations contract を定義すれば、browser, CLI, future automation の間で business operation を共有しやすい
- view / form に直接ドメイン操作を埋め込まずに済む

### 2. Repo fit

- 現行 repo は Python 中心であり、operations layer もそのまま Python に置くのが自然
- crawler 本体を別言語 stack に移し替える必要がない
- Cloud Run 上で machine-facing API と human-facing UI を同じ技術基盤で運用しやすい

### 3. Operator workflow fit

- Django は auth, session, permission, admin, form handling が揃っており、internal operator UI を短距離で作りやすい
- ただし UI 都合で framework choice を決め打ちせず、typed operations layer を中心に据えることで将来の surface 追加にも耐えやすい

## Rejected Alternatives

### Option A: Human-only Django admin first

短期的には最速だが、browser 向けの view / form がそのまま業務操作の本体になりやすい。  
その形だと LLM/tool client 向け interface をあとから追加する際に、二つ目の操作面を別途設計し直す可能性が高い。

### Option B: Next.js App Router as primary interface

長期的に public-facing SaaS frontend を強く作るなら有力だが、初期の internal admin には過剰。  
現時点で Node.js / TypeScript ランタイム、認証基盤、API 境界を新設すると、repo fit より構成複雑化のコストが先に来る。

### Option C: FastAPI + separate React frontend

API と UI の分離は明快だが、internal admin の立ち上がりとしては境界が多すぎる。  
今回必要なのは「分離された transport」より「共通 operations contract」であり、その contract があれば UI は Django でも十分成立する。

## Non-Goals

- 最初から public SaaS 向け polished frontend を作ること
- いきなり SPA / BFF / microservices に分割すること
- crawler のドメインロジックを Django app へ全面移植すること
- local/json backend にない persistence contract を Phase 1 で暗黙追加すること
- billing / subscription をこの段階で設計根拠に持ち込むこと
- Discord や GCP 運用導線をすぐに置き換えること

## Functional Requirements For Phase 1

Phase 1 は browser UI より先に、共通 operations contract を成立させる。

1. watchlist / state / health / manual run を扱う typed command/query operations layer を定義する
2. 同じ operations layer を machine-facing JSON API から呼べるようにする
3. 同じ operations layer を internal browser UI から呼べるようにする
4. watchlist の一覧表示、追加、編集、無効化は view 直書きではなく shared operation を経由する
5. state の latest / unread / health は machine surface と human surface の両方で一貫した query 結果を返す
6. manual run は shared operation を経由して起動し、二重実行防止や validation を transport ごとに複製しない
7. run summary の履歴表示は backend capability に従う
8. Phase 1 で promises する run history は Firestore backend に persisted summary がある場合に限る
9. file backend では「最近の run 一覧」は約束せず、未対応 capability として明示する
10. human auth と machine auth は transport ごとに分け、session/cookie と API credential を混同しない

## Proposed Architecture

### High-level shape

`manga_watch` をドメイン層として温存し、その上に typed operations layer を追加する。  
browser UI と machine-facing API はどちらも同じ operations layer を使い、transport ごとの validation や整形だけを担当する。

```text
Human browser
  -> Django SSR views / forms
    -> operations layer
      -> manga_watch domain modules
        -> storage / runner / notifier / source adapters

LLM / internal tools
  -> JSON API / OpenAPI
    -> operations layer
      -> manga_watch domain modules
        -> storage / runner / notifier / source adapters
```

### Operations-first rule

**業務操作の本体は views でも API handlers でもなく、typed operations layer に置く。**

- view は HTML form と session auth を扱う
- API handler は JSON serialization と machine auth を扱う
- operation は validation 済み input を受けて domain module を呼び、typed result を返す

この境界を守ることで、browser と machine client の振る舞い差分を transport 層に閉じ込めやすい。

## Interface Model

### Typed command/query split

operations layer は少なくとも次の 2 種類に分ける。

- `queries`: watchlist, state, health, supported capabilities の取得
- `commands`: watchlist mutation, manual run, maintenance action の起動

### Transport contract

- machine surface は JSON response を返す
- schema は OpenAPI で記述し、LLM/tool client が安定して使える契約にする
- human UI は同じ query/command を呼び、HTML と form error に変換する

### Capability reporting

backend 差異を隠しきれない機能は、曖昧に degrade させず capability として明示する。

例:

- `run_history_supported = true` for Firestore
- `run_history_supported = false` for file backend

## Project Structure

初期案として、repo 直下に Web project 用ディレクトリを追加する。

```text
web_admin/
  manage.py
  project/
    settings.py
    urls.py
    wsgi.py
    asgi.py
  operations/
    commands.py
    queries.py
    schemas.py
    capabilities.py
  api/
    urls.py
    views.py
    auth.py
    openapi.py
  ui/
    urls.py
    views.py
    forms.py
    templates/ui/
  shared/
    auth.py
    navigation.py
```

### Responsibility split

- `manga_watch/`: crawler / state / storage / domain behavior
- `web_admin/operations/`: transport-independent application operations
- `web_admin/api/`: machine-facing JSON / OpenAPI surface
- `web_admin/ui/`: human-facing Django UI
- `shared/`: common auth helpers, navigation, presentation helpers

## UI Strategy

### Rendering model

- 基本は Django template による SSR
- filter, inline toggle, confirmation modal など、小さい振る舞いだけ軽い JS を足す
- 初期段階では frontend build pipeline を前提にしない

### Constraint

UI は primary interface ではない。  
画面でできる操作も API でできる操作も、同じ command/query を通す。

## Authentication Strategy

### Human surface

- Django 標準 auth を利用する
- app 全体を login required にする
- destructive action は CSRF 保護と POST 限定を徹底する
- 最初は単一管理者アカウントを前提にする

### Machine surface

- session cookie は使わない
- bearer token か service-to-service credential のどちらかで認証する
- credential source は implementation で確定するが、Cloud Run / Secret Manager 運用と整合する方式を選ぶ
- machine auth は human session と別に管理する

## Deployment Strategy

### Initial deployment model

- machine-facing API と human-facing UI は同じ Django project で提供してよい
- crawler job とは別 service として分離する
- browser-facing admin 専用の新しい Cloud Run Service を作る

### Recommendation

初期実装では **別 Cloud Run Service** を採用する。  
理由は、Discord interaction endpoint と operator-facing service では request profile, auth, rollout cadence が異なるため。  
service 名は implementation で確定するが、`comic-crawler-web` のように役割が明確な名前を推奨する。

## Data Access Strategy

Web project は storage backend の source of truth を尊重する。

### Rules

- watchlist / state は既存 storage abstraction を通じて読む
- Web 用に別 schema を先に作らない
- transport の都合で domain persistence contract を書き換えない

### Run summary caveat

現状の storage contract では、`record_run_summary()` は Firestore backend のときだけ persistence され、file backend では `None` を返す。  
そのため Phase 1 では backend-neutral な run history 一覧を約束しない。

### Phase 1 behavior

- Firestore backend: persisted run summary 一覧を expose してよい
- file backend: run history capability を `unsupported` として返す
- 両 backend 共通で必要な場合は、後続 milestone で backend-neutral run history repository を追加する

## Testing Strategy

### Phase 1 tests

- operations layer の unit / integration tests
- machine-facing API contract tests
- Django UI が shared operations を呼ぶことの tests
- auth boundary tests
- existing `manga_watch` contract を壊していないことの regression tests

### Priorities

1. human と machine が同じ operation result を共有すること
2. watchlist 編集が既存 contract を壊さないこと
3. manual run 導線が誤って複数回同時実行されないこと
4. file backend で unsupported capability が明示的に返ること
5. Firestore backend で run history が期待どおり expose されること

## Migration Path

### Milestone 1

- operations layer scaffold
- typed query/command schemas
- machine auth 方針の確定
- read-only JSON API for watchlist / state / health / capabilities

### Milestone 2

- Django login
- read-only browser dashboard backed by shared queries
- watchlist mutation commands exposed via API and UI
- manual run trigger exposed via API and UI

### Milestone 3

- Firestore-backed run summary view
- file backend での capability 表示
- safer operations UX
- role split / audit trail

### Milestone 4

- backend-neutral run history repository が必要か再判定
- 必要な場合のみ persistence contract を拡張

## Risks

### Risk 1: API and UI drift

UI 用の近道実装を始めると、operation の本体が transport ごとに分岐しやすい。  
これを避けるため、command/query を transport-independent に保つ。

### Risk 2: Backend capability mismatch

Firestore と file backend の差を UI 都合で隠そうとすると、存在しない persistence を暗黙に期待してしまう。  
対応方針は degrade ではなく capability 明示にする。

### Risk 3: Human auth and machine auth confusion

internal service でも browser session と tool credential を混ぜると運用事故につながる。  
surface ごとに認証方式を分け、権限境界も別管理にする。

## Future Notes

将来 public-facing product や課金が必要になっても、まず再利用すべきなのは operations contract である。  
billing や subscription はこの framework decision の根拠には含めず、実際に public product 要件が固まった時点で別 spec として扱う。

## Recommendation Summary

この repo の Web 基盤は、まず **operations-first の Python contract を定義し、その上に machine-facing JSON API と thin Django UI を載せる**のが最も現実的である。  
Django は internal operator UI として引き続き適しているが、primary interface は typed operations layer であり、backend 差異は capability として明示する。  
これにより、human operator と LLM/tool client の両方に一貫した操作面を提供できる。

## Sources

- Django admin docs: <https://docs.djangoproject.com/en/stable/ref/contrib/admin/>
- Django auth docs: <https://docs.djangoproject.com/en/6.0/topics/auth/>
- Django release process: <https://docs.djangoproject.com/en/6.0/internals/release-process/>
- Cloud Run Django guide: <https://cloud.google.com/python/django/run>
- Next.js App Router docs: <https://nextjs.org/docs/app>
- Next.js authentication docs: <https://nextjs.org/docs/app/building-your-application/authentication>
