import unittest
from pathlib import Path
import json
import tempfile

from manga_watch.discord_add import (
    ADD_MISSING_URL_MESSAGE,
    AddCommandHandler,
)
from manga_watch.watchlist import WatchlistAddError, add_watchlist_url


class DiscordAddTests(unittest.TestCase):
    def test_start_returns_missing_url_message_when_url_is_empty(self):
        handler = AddCommandHandler()

        payload = handler.start(url="  ")

        self.assertEqual(ADD_MISSING_URL_MESSAGE, payload["content"])

    def test_start_formats_added_result(self):
        def add_subscription(url, *, watchlist_path=None):
            self.assertEqual("https://kakuyomu.jp/works/123", url)
            self.assertEqual("watchlist.json", watchlist_path)
            return {
                "action": "added",
                "entry": {
                    "id": "kakuyomu:123",
                    "seed_url": "https://kakuyomu.jp/works/123",
                },
            }

        handler = AddCommandHandler(add_subscription=add_subscription)

        payload = handler.start(
            url="https://kakuyomu.jp/works/123",
            watchlist_path="watchlist.json",
        )

        self.assertIn("追加しました", payload["content"])
        self.assertIn("kakuyomu:123", payload["content"])

    def test_start_formats_duplicate_result(self):
        handler = AddCommandHandler(
            add_subscription=lambda *_args, **_kwargs: {
                "action": "duplicate",
                "entry": {"id": "kakuyomu:123"},
                "existing": {"seed_url": "https://kakuyomu.jp/works/123"},
            }
        )

        payload = handler.start(url="https://kakuyomu.jp/works/123")

        self.assertIn("既に登録済み", payload["content"])

    def test_start_formats_watchlist_error(self):
        def add_subscription(_url, *, watchlist_path=None):
            raise WatchlistAddError(
                "unsupported_source",
                "Unsupported source host: example.com",
                "Use one of the supported sources.",
            )

        handler = AddCommandHandler(add_subscription=add_subscription)

        payload = handler.start(url="https://example.com/work/1")

        self.assertIn("追加できませんでした", payload["content"])
        self.assertIn("Unsupported source host: example.com", payload["content"])

    def test_start_accepts_nicovideo_sp_comic_url_via_watchlist_logic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            watchlist_path.write_text(
                json.dumps({"version": 2, "works": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            handler = AddCommandHandler(
                add_subscription=lambda url, *, watchlist_path=None: add_watchlist_url(
                    url,
                    watchlist_path=watchlist_path,
                )
            )

            payload = handler.start(
                url="https://sp.manga.nicovideo.jp/comic/53764?track=share",
                watchlist_path=str(watchlist_path),
            )

        self.assertIn("追加しました", payload["content"])
        self.assertIn("nicovideo-manga:53764", payload["content"])


if __name__ == "__main__":
    unittest.main()
