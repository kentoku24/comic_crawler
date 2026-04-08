import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from manga_watch.watchlist import WatchlistAddError, add_watchlist_url


def write_watchlist(path: Path, works):
    path.write_text(
        json.dumps({"version": 2, "works": works}, ensure_ascii=False),
        encoding="utf-8",
    )


class StaticHttpClient:
    def __init__(self, responses):
        self.responses = dict(responses)

    def get_text(self, url: str) -> str:
        if url not in self.responses:
            raise AssertionError(f"unexpected request: {url!r}")
        return self.responses[url]


class WatchlistAddLogicTests(unittest.TestCase):
    maxDiff = None

    def test_add_watchlist_url_adds_entry_from_supported_work_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://kakuyomu.jp/works/123",
                watchlist_path=str(watchlist_path),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("kakuyomu:123", payload["entry"]["id"])
        self.assertEqual("https://kakuyomu.jp/works/123", payload["entry"]["seed_url"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_add_watchlist_url_reports_duplicate_without_writing_second_entry(self):
        existing_entry = {
            "id": "kakuyomu:123",
            "source": "kakuyomu",
            "seed_url": "https://kakuyomu.jp/works/123/episodes/456",
            "enabled": True,
            "notification_policy": {"mode": "all", "allowed_update_types": None},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [existing_entry])

            payload = add_watchlist_url(
                "https://kakuyomu.jp/works/123",
                watchlist_path=str(watchlist_path),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("duplicate", payload["action"])
        self.assertEqual(existing_entry, payload["existing"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual([existing_entry], saved["works"])

    def test_add_watchlist_url_adds_entry_from_comic_action_series_feed_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://comic-action.com/rss/series/13933686331606207128?free_only=1",
                watchlist_path=str(watchlist_path),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("comic-action:13933686331606207128", payload["entry"]["id"])
        self.assertEqual(
            "https://comic-action.com/rss/series/13933686331606207128",
            payload["entry"]["seed_url"],
        )
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_add_watchlist_url_reports_duplicate_for_comic_action_series_feed_url(self):
        existing_entry = {
            "id": "comic-action:13933686331606207128",
            "source": "comic-action",
            "seed_url": "https://comic-action.com/episode/11341664176570134078",
            "enabled": True,
            "notification_policy": {"mode": "all", "allowed_update_types": None},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [existing_entry])

            payload = add_watchlist_url(
                "https://comic-action.com/atom/series/13933686331606207128",
                watchlist_path=str(watchlist_path),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("duplicate", payload["action"])
        self.assertEqual(existing_entry, payload["existing"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual([existing_entry], saved["works"])

    def test_add_watchlist_url_accepts_champion_cross_episode_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://championcross.jp/episodes/f35108c56e75d/?utm_source=rss&utm_medium=referral",
                watchlist_path=str(watchlist_path),
                http_client=StaticHttpClient(
                    {
                        "https://championcross.jp/episodes/f35108c56e75d": """
                        <html>
                          <body>
                            <a href="https://championcross.jp/series/4756324e1c1b1/rss">RSS</a>
                          </body>
                        </html>
                        """
                    }
                ),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("champion-cross:4756324e1c1b1", payload["entry"]["id"])
        self.assertEqual(
            "https://championcross.jp/episodes/f35108c56e75d",
            payload["entry"]["seed_url"],
        )
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_add_watchlist_url_accepts_magapoke_episode_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://pocket.shonenmagazine.com/title/03021/episode/427856?utm_source=share",
                watchlist_path=str(watchlist_path),
                http_client=StaticHttpClient(
                    {
                        "https://pocket.shonenmagazine.com/title/03021": """
                        <html>
                          <head>
                            <link rel="alternate" type="application/rss+xml" href="https://mgpk-cdn.magazinepocket.com/static/rss/3021/feed.xml">
                          </head>
                          <body></body>
                        </html>
                        """
                    }
                ),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("magapoke:3021", payload["entry"]["id"])
        self.assertEqual(
            "https://pocket.shonenmagazine.com/title/03021",
            payload["entry"]["seed_url"],
        )
        self.assertEqual("magapoke", payload["entry"]["source"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_add_watchlist_url_accepts_takecomic_series_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://takecomic.jp/series/3f846451aff2d/?utm_source=share",
                watchlist_path=str(watchlist_path),
                http_client=StaticHttpClient({}),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("takecomic:3f846451aff2d", payload["entry"]["id"])
        self.assertEqual(
            "https://takecomic.jp/series/3f846451aff2d",
            payload["entry"]["seed_url"],
        )
        self.assertEqual("takecomic", payload["entry"]["source"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_add_watchlist_url_accepts_shonenjumpplus_episode_url_and_canonicalizes_to_rss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://shonenjumpplus.com/episode/17107419589191805801?from=share",
                watchlist_path=str(watchlist_path),
                http_client=StaticHttpClient(
                    {
                        "https://shonenjumpplus.com/episode/17107419589191805801": """
                        <html>
                          <head>
                            <title>[159話]マリッジトキシン - 静脈/依田瑞稀 | 少年ジャンプ＋</title>
                            <link rel="alternate" type="application/rss+xml" href="https://shonenjumpplus.com/rss/series/3269754496881854342">
                          </head>
                          <body></body>
                        </html>
                        """
                    }
                ),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("shonenjumpplus:3269754496881854342", payload["entry"]["id"])
        self.assertEqual(
            "https://shonenjumpplus.com/rss/series/3269754496881854342",
            payload["entry"]["seed_url"],
        )
        self.assertEqual("shonenjumpplus", payload["entry"]["source"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_add_watchlist_url_accepts_comicborder_episode_url_and_canonicalizes_to_rss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://comicborder.com/episode/12207421983437812169?from=share",
                watchlist_path=str(watchlist_path),
                http_client=StaticHttpClient(
                    {
                        "https://comicborder.com/episode/12207421983437812169": """
                        <html>
                          <head>
                            <title>マヨネーズ王は貧乏になりたい！【男女比１：１００】世界で逝く勘違い出世街道 - 神影龍之介/馬路まんじ / 第01話 死んでサイタマ　～異世界全方位成り上がりRTA開始（※望んでない）～ | コミックボーダー</title>
                            <link rel="alternate" type="application/rss+xml" href="https://comicborder.com/rss/series/12207421983437805229">
                          </head>
                          <body></body>
                        </html>
                        """
                    }
                ),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("comicborder:12207421983437805229", payload["entry"]["id"])
        self.assertEqual(
            "https://comicborder.com/rss/series/12207421983437805229",
            payload["entry"]["seed_url"],
        )
        self.assertEqual("comicborder", payload["entry"]["source"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_add_watchlist_url_accepts_firecross_reader_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://firecross.jp/reader/19386?trial=0&token=temp&vertical=0",
                watchlist_path=str(watchlist_path),
                http_client=StaticHttpClient(
                    {
                        "https://firecross.jp/reader/19386": """
                        <html>
                          <body>
                            <a href="https://firecross.jp/series/series-abc">作品詳細</a>
                          </body>
                        </html>
                        """
                    }
                ),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("firecross:series-abc", payload["entry"]["id"])
        self.assertEqual(
            "https://firecross.jp/reader/19386",
            payload["entry"]["seed_url"],
        )
        self.assertEqual("firecross", payload["entry"]["source"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_add_watchlist_url_accepts_firecross_ebook_series_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://firecross.jp/ebook/series/358?sort=latest",
                watchlist_path=str(watchlist_path),
                http_client=StaticHttpClient({}),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("firecross:358", payload["entry"]["id"])
        self.assertEqual(
            "https://firecross.jp/ebook/series/358",
            payload["entry"]["seed_url"],
        )
        self.assertEqual("firecross", payload["entry"]["source"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_watchlist_add_accepts_nicovideo_sp_comic_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            payload = add_watchlist_url(
                "https://sp.manga.nicovideo.jp/comic/53764?track=share",
                watchlist_path=str(watchlist_path),
                http_client=StaticHttpClient({}),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual("added", payload["action"])
        self.assertEqual("nicovideo-manga:53764", payload["entry"]["id"])
        self.assertEqual(
            "https://manga.nicovideo.jp/comic/53764",
            payload["entry"]["seed_url"],
        )
        self.assertEqual("nicovideo-manga", payload["entry"]["source"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_watchlist_add_reports_unsupported_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

class WatchlistCliRetirementTests(unittest.TestCase):
    maxDiff = None

    def run_watchlist_module(self, *args):
        repo_root = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [sys.executable, "-m", "manga_watch.watchlist", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_watchlist_cli_reports_deprecated_when_called_with_add(self):
        result = self.run_watchlist_module("add", "https://example.com/work/1")

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("error", payload["action"])
        self.assertEqual("deprecated_cli", payload["error"]["kind"])
        self.assertIn("retired", payload["error"]["message"])
        self.assertIn("/add", payload["error"]["next_action"])

    def test_watchlist_cli_reports_deprecated_without_arguments(self):
        result = self.run_watchlist_module()

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("error", payload["action"])
        self.assertEqual("deprecated_cli", payload["error"]["kind"])

    def test_add_watchlist_url_reports_unsupported_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            with self.assertRaisesRegex(WatchlistAddError, "Unsupported source host: example.com"):
                add_watchlist_url(
                    "https://example.com/work/1",
                    watchlist_path=str(watchlist_path),
                )

    def test_add_watchlist_url_reports_unsupported_url_type_for_supported_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            with self.assertRaisesRegex(
                WatchlistAddError,
                "does not support this URL type for work registration",
            ):
                add_watchlist_url(
                    "https://comic-action.com/series/123",
                    watchlist_path=str(watchlist_path),
                )

    def test_add_watchlist_url_reports_unsupported_url_type_for_firecross_series_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            with self.assertRaisesRegex(
                WatchlistAddError,
                "does not support this URL type for work registration",
            ):
                add_watchlist_url(
                    "https://firecross.jp/series/series-abc",
                    watchlist_path=str(watchlist_path),
                )

    def test_add_watchlist_url_reports_invalid_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            with self.assertRaisesRegex(
                WatchlistAddError,
                "Input must be an absolute http\\(s\\) URL",
            ):
                add_watchlist_url(
                    "not-a-url",
                    watchlist_path=str(watchlist_path),
                )


if __name__ == "__main__":
    unittest.main()
