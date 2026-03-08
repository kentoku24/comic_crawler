# Fixture Bundles

`tests/fixtures/<source>/<case>/` は 1 case = 1 ordered response bundle です。`manifest.json` が seed URL と期待値を持ち、`01-*.html`, `02-*.html`, ... が adapter が実際に読む raw response を順序付きで保持します。

## Layout

- `manifest.json`: `seedUrl`, `expectedWork`, `steps`, `expectedLatest` または `expectedError`
- `01-*.html`, `02-*.html`, ...: parser が読む raw payload。HTML の prettify や JSON の再直列化はしない

## Refresh Procedure

1. Adapter がたどる順序どおりに raw response を取得する。更新時は取得日を PR description または commit message に残す
2. レスポンス本文は parser が読む形のまま保存する。`__NEXT_DATA__`, `nextReadableProductUri`, HTML escaping, `<title>` は壊さない
3. サニタイズは parser に不要な値だけに限定する。cookie, token, viewer id, tracking query, 個人情報は除去してよいが、episode code, `publishedAt`, title, parser が参照する DOM 断片は保持する
4. `manifest.json` の期待値を更新し、`.venv/bin/python -m unittest tests.test_sources tests.test_check` を実行する

## Notes

- この initial suite は 2026-03-07 時点の regression foundation として追加している
- same stable id の metadata 改善ケースは fixture と state transition test の両方で固定する
