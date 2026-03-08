import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def write_watchlist(path: Path, works):
    path.write_text(
        json.dumps({"version": 2, "works": works}, ensure_ascii=False),
        encoding="utf-8",
    )


class WatchlistCliTests(unittest.TestCase):
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

    def test_watchlist_add_adds_entry_from_supported_work_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            result = self.run_watchlist_module(
                "add",
                "https://kakuyomu.jp/works/123",
                "--watchlist",
                str(watchlist_path),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("added", payload["action"])
        self.assertEqual("kakuyomu:123", payload["entry"]["id"])
        self.assertEqual("https://kakuyomu.jp/works/123", payload["entry"]["seed_url"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual(1, len(saved["works"]))

    def test_watchlist_add_reports_duplicate_without_writing_second_entry(self):
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

            result = self.run_watchlist_module(
                "add",
                "https://kakuyomu.jp/works/123",
                "--watchlist",
                str(watchlist_path),
            )
            saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("duplicate", payload["action"])
        self.assertEqual(existing_entry, payload["existing"])
        self.assertEqual(1, payload["work_count"])
        self.assertEqual([existing_entry], saved["works"])

    def test_watchlist_add_reports_unsupported_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            result = self.run_watchlist_module(
                "add",
                "https://example.com/work/1",
                "--watchlist",
                str(watchlist_path),
            )

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("error", payload["action"])
        self.assertEqual("unsupported_source", payload["error"]["kind"])

    def test_watchlist_add_reports_unsupported_url_type_for_supported_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            result = self.run_watchlist_module(
                "add",
                "https://comic-action.com/series/123",
                "--watchlist",
                str(watchlist_path),
            )

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("error", payload["action"])
        self.assertEqual("unsupported_url_type", payload["error"]["kind"])

    def test_watchlist_add_reports_invalid_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            result = self.run_watchlist_module(
                "add",
                "not-a-url",
                "--watchlist",
                str(watchlist_path),
            )

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("error", payload["action"])
        self.assertEqual("invalid_url", payload["error"]["kind"])


if __name__ == "__main__":
    unittest.main()
