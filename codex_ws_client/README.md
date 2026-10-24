# Codex App Server WebSocket Client Container

`https://developers.openai.com/codex/app-server` を利用する外部 AI アプリ（自作アプリ / Claude / openclaw 等）向けに、最小限のセキュアな OAuth ハンドオフ + WS proxy 土台を提供します。

## フロー

1. `GET /auth/url` を叩いて認証 URL を取得。
2. ユーザーがブラウザで認証し、リダイレクトされた **最終 URL 全体** をコピー。
3. `POST /auth/callback-url` に URL を渡して code/state 検証 + token exchange。
4. `POST /ws/proxy` を自作クライアントの relay endpoint として利用（現状は接続土台の返却）。

## 起動

```bash
cd codex_ws_client
cp .env.example .env
# 必須値を埋める

docker compose up --build -d
```

## API

- `GET /healthz`
- `GET /auth/url`（`Authorization: Bearer <ADMIN_TOKEN>` 推奨）
- `POST /auth/callback-url`
  - body: `{ "callback_url": "https://...?...code=...&state=..." }`
- `POST /ws/proxy`

## セキュリティ

- `state + PKCE(S256)`
- token / session は `/data/session.enc` へ Fernet で暗号化保存
- `ADMIN_TOKEN` で管理 API 保護
- localhost bind (`127.0.0.1:8080`)
- Docker hardening: `read_only`, `cap_drop: [ALL]`, `no-new-privileges`

## 注意

- 実際の app-server の websocket protocol は変化し得るため、`/ws/proxy` の downstream 実装は運用時に調整してください。
