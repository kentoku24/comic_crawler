import json
import os
import tempfile
import unittest
from unittest import mock

from manga_watch import check


class CheckTests(unittest.TestCase):
    def test_run_check_initializes_state_without_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            urls_path = os.path.join(tmpdir, "urls.txt")
            state_path = os.path.join(tmpdir, "state.json")
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write("https://example.com/work\n")

            latest = {
                "seriesTitle": "作品A",
                "episodeTitle": "第1話",
                "url": "https://example.com/work/1",
            }

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": state_path}, clear=False):
                with mock.patch(
                    "manga_watch.check.normalize_item",
                    return_value={"kind": "fake", "seedUrl": "https://example.com/work"},
                ):
                    with mock.patch("manga_watch.check.compute_latest", return_value=latest):
                        result = check.run_check(urls_path)

            self.assertEqual({"updates": []}, result)
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.assertIn("https://example.com/work", state["items"])

    def test_run_check_reports_updates_when_latest_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            urls_path = os.path.join(tmpdir, "urls.txt")
            state_path = os.path.join(tmpdir, "state.json")
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write("https://example.com/work\n")

            first = {
                "seriesTitle": "作品A",
                "episodeTitle": "第1話",
                "url": "https://example.com/work/1",
            }
            second = {
                "seriesTitle": "作品A",
                "episodeTitle": "第2話",
                "url": "https://example.com/work/2",
            }

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": state_path}, clear=False):
                with mock.patch(
                    "manga_watch.check.normalize_item",
                    return_value={"kind": "fake", "seedUrl": "https://example.com/work"},
                ):
                    with mock.patch("manga_watch.check.compute_latest", side_effect=[first, second]):
                        check.run_check(urls_path)
                        result = check.run_check(urls_path)

            self.assertEqual(1, len(result["updates"]))
            self.assertEqual("第1話", result["updates"][0]["from"]["episodeTitle"])
            self.assertEqual("第2話", result["updates"][0]["to"]["episodeTitle"])


if __name__ == "__main__":
    unittest.main()
