import json
import os
import tempfile
import unittest
from unittest import mock

from manga_watch import check
from manga_watch.sources import LatestEpisode, SourceAdapter, WorkDescriptor


class FakeAdapter(SourceAdapter):
    source = "fake"

    def __init__(self, latest_keys):
        self.latest_keys = list(latest_keys)

    def can_handle(self, seed_url: str) -> bool:
        return seed_url == "https://example.com/work"

    def normalize(self, seed_url: str) -> WorkDescriptor:
        return WorkDescriptor(
            source=self.source,
            work_id="work-1",
            seed_url=seed_url,
        )

    def fetch_latest(self, work: WorkDescriptor, http_client) -> LatestEpisode:
        latest_key = self.latest_keys.pop(0)
        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_key,
            url=f"https://example.com/{latest_key}",
            episode_title=latest_key,
        )


class CheckTests(unittest.TestCase):
    def test_normalize_item_returns_work_descriptor_fields(self):
        item = check.normalize_item("https://kakuyomu.jp/works/123/episodes/456")

        self.assertEqual("kakuyomu", item["source"])
        self.assertEqual("kakuyomu:123", item["workId"])
        self.assertEqual("456", item["seedEpisodeId"])

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

    def test_run_check_compares_using_latest_key_from_adapter_interface(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            urls_path = os.path.join(tmpdir, "urls.txt")
            state_path = os.path.join(tmpdir, "state.json")
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write("https://example.com/work\n")

            adapter = FakeAdapter(["ep-1", "ep-2"])

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": state_path}, clear=False):
                check.run_check(urls_path, adapters=[adapter])
                result = check.run_check(urls_path, adapters=[adapter])

            self.assertEqual(1, len(result["updates"]))
            self.assertEqual("ep-1", result["updates"][0]["from"]["latestKey"])
            self.assertEqual("ep-2", result["updates"][0]["to"]["latestKey"])

            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.assertEqual("ep-2", state["items"]["work-1"]["latest"]["latestKey"])


if __name__ == "__main__":
    unittest.main()
