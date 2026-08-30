# Codex Approval Menubar MVP

Codex がユーザー承認を求めたときに、**許可すべきかの判断材料**をすぐ返すための macOS menubar app の骨格です。

## Current scope

このディレクトリは SwiftUI `MenuBarExtra` ベースの **MVP scaffold** です。
まだ Codex の実イベント監視には接続しておらず、まずは次を確認できます。

- assessment API endpoint の設定
- command / cwd / source / justification の入力
- `/api/codex/approval-assess/` への POST
- risk / recommendation / reasons の表示
- 高リスク時のローカル通知
- sample request の切り替え

## Run

```bash
cd apps/codex_approval_menubar
swift run
```

## Expected backend

既定では次の endpoint を叩きます。

- `http://127.0.0.1:8000/api/codex/approval-assess/`

必要なら menubar UI で endpoint を直接書き換えてください。

## Next steps

1. Codex approval event を監視する bridge を足す
2. bridge からこのアプリへ event を流す
3. request history の永続化
4. approve / deny 操作の検討

## Notes

- 本体の判定ロジックは Swift 側ではなく Python backend を source of truth にする
- Swift 側は「通知と判断表示の surface」に寄せる
