import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manga_watch import check
from manga_watch.sources import LatestEpisode, SourceAdapter, WorkDescriptor
from manga_watch.sources.base import SourceParseError


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
    def run_check_module(self, urls_path, *, extra_env=None):
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "manga_watch.check", str(urls_path)],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_check_module_runs_via_python_m(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            urls_path = Path(tmpdir) / "urls.txt"
            state_path = Path(tmpdir) / "state.json"
            urls_path.write_text("", encoding="utf-8")

            result = self.run_check_module(
                urls_path,
                extra_env={"MANGA_WATCH_STATE": str(state_path)},
            )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual(
            {"updates": [], "errors": {"sources": [], "run": []}},
            json.loads(result.stdout),
        )

    def test_check_module_reports_read_urls_failures_as_json(self):
        missing_urls_path = Path(tempfile.gettempdir()) / "comic-crawler-missing-urls.txt"
        if missing_urls_path.exists():
            missing_urls_path.unlink()

        result = self.run_check_module(missing_urls_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual(
            {
                "updates": [],
                "errors": {
                    "sources": [],
                    "run": [
                        {
                            "stage": "read_urls",
                            "kind": "runtime",
                            "errorType": "FileNotFoundError",
                            "message": f"[Errno 2] No such file or directory: '{missing_urls_path}'",
                        }
                    ],
                },
            },
            json.loads(result.stdout),
        )
        self.assertEqual("", result.stderr)

    def test_check_module_reports_load_state_failures_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            urls_path = Path(tmpdir) / "urls.txt"
            state_path = Path(tmpdir) / "state.json"
            urls_path.write_text("", encoding="utf-8")
            state_path.write_text("{broken json", encoding="utf-8")

            result = self.run_check_module(
                urls_path,
                extra_env={"MANGA_WATCH_STATE": str(state_path)},
            )

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual([], payload["updates"])
        self.assertEqual([], payload["errors"]["sources"])
        self.assertEqual("load_state", payload["errors"]["run"][0]["stage"])
        self.assertEqual("JSONDecodeError", payload["errors"]["run"][0]["errorType"])
        self.assertEqual("", result.stderr)

    def test_check_module_reports_save_state_failures_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            urls_path = Path(tmpdir) / "urls.txt"
            urls_path.write_text("", encoding="utf-8")

            result = self.run_check_module(
                urls_path,
                extra_env={"MANGA_WATCH_STATE": "/dev/null/state.json"},
            )

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual([], payload["updates"])
        self.assertEqual([], payload["errors"]["sources"])
        self.assertEqual("save_state", payload["errors"]["run"][0]["stage"])
        self.assertEqual("FileExistsError", payload["errors"]["run"][0]["errorType"])
        self.assertEqual("", result.stderr)

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

            self.assertEqual([], result["updates"])
            self.assertEqual({"sources": [], "run": []}, result["errors"])
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.assertIn("https://example.com/work", state["items"])

    def test_apply_item_transition_reports_updates_when_latest_changes(self):
        previous = {
            "latest": {
                "latestKey": "ep-1",
                "seriesTitle": "作品A",
                "episodeTitle": "第1話",
                "url": "https://example.com/work/1",
            },
            "seenAt": 10,
        }
        latest = {
            "latestKey": "ep-2",
            "seriesTitle": "作品A",
            "episodeTitle": "第2話",
            "url": "https://example.com/work/2",
        }

        next_entry, update = check.apply_item_transition(
            "work-1",
            previous,
            latest,
            seen_at=20,
        )

        self.assertEqual({"latest": latest, "seenAt": 20}, next_entry)
        self.assertEqual(
            {"id": "work-1", "from": previous["latest"], "to": latest},
            update,
        )

    def test_apply_item_transition_silently_merges_metadata_when_latest_key_is_stable(self):
        previous = {
            "latest": {
                "latestKey": "ep-1",
                "seriesTitle": "旧タイトル",
                "episodeTitle": "旧サブタイトル",
                "pageTitle": "",
                "url": "https://example.com/work/1",
                "summary": "",
            },
            "seenAt": 10,
        }
        latest = {
            "latestKey": "ep-1",
            "seriesTitle": "新タイトル",
            "episodeTitle": "新サブタイトル",
            "pageTitle": "作品A 第1話",
            "url": "https://example.com/work/1?ref=canonical",
            "summary": "補足",
        }

        next_entry, update = check.apply_item_transition(
            "work-1",
            previous,
            latest,
            seen_at=20,
        )

        self.assertIsNone(update)
        self.assertEqual(20, next_entry["seenAt"])
        self.assertEqual("新タイトル", next_entry["latest"]["seriesTitle"])
        self.assertEqual("新サブタイトル", next_entry["latest"]["episodeTitle"])
        self.assertEqual("作品A 第1話", next_entry["latest"]["pageTitle"])
        self.assertEqual("補足", next_entry["latest"]["summary"])
        self.assertEqual(
            "https://example.com/work/1",
            next_entry["latest"]["url"],
        )

    def test_error_records_distinguish_source_parse_and_run_failures(self):
        parse_error = check.source_error_record(
            "https://example.com/work",
            item_id="work-1",
            phase="fetch_latest",
            exc=SourceParseError("bad markup"),
        )
        run_error = check.run_error_record("save_state", RuntimeError("disk full"))

        self.assertEqual("parse", parse_error["kind"])
        self.assertEqual("SourceParseError", parse_error["errorType"])
        self.assertEqual(
            {
                "stage": "save_state",
                "kind": "runtime",
                "errorType": "RuntimeError",
                "message": "disk full",
            },
            run_error,
        )

    def test_run_check_raises_structured_run_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            urls_path = os.path.join(tmpdir, "urls.txt")
            state_path = os.path.join(tmpdir, "state.json")
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write("https://example.com/work\n")

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": state_path}, clear=False):
                with mock.patch(
                    "manga_watch.check.normalize_item",
                    return_value={"kind": "fake", "seedUrl": "https://example.com/work"},
                ):
                    with mock.patch(
                        "manga_watch.check.compute_latest",
                        return_value={"latestKey": "ep-1", "url": "https://example.com/work/1"},
                    ):
                        with mock.patch(
                            "manga_watch.check.save_state",
                            side_effect=OSError("disk full"),
                        ):
                            with self.assertRaises(check.CheckRunError) as ctx:
                                check.run_check(urls_path)

        self.assertEqual("save_state", ctx.exception.stage)
        self.assertEqual(
            [
                {
                    "stage": "save_state",
                    "kind": "runtime",
                    "errorType": "OSError",
                    "message": "disk full",
                }
            ],
            ctx.exception.result["errors"]["run"],
        )
        self.assertEqual([], ctx.exception.result["errors"]["sources"])

    def test_run_check_keeps_successful_updates_when_other_sources_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            urls_path = os.path.join(tmpdir, "urls.txt")
            state_path = os.path.join(tmpdir, "state.json")
            urls = [
                "https://example.com/work/a",
                "https://example.com/work/b",
                "https://example.com/work/c",
            ]
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write("\n".join(urls) + "\n")

            items = {
                urls[0]: {"kind": "fake", "workId": "work-a", "seedUrl": urls[0]},
                urls[1]: {"kind": "fake", "workId": "work-b", "seedUrl": urls[1]},
                urls[2]: {"kind": "fake", "workId": "work-c", "seedUrl": urls[2]},
            }
            call_count = {"work-a": 0, "work-b": 0, "work-c": 0}

            def fake_normalize(url, adapters=None):
                return dict(items[url])

            def fake_latest(item, adapters=None, http_client=None):
                work_id = item["workId"]
                call_count[work_id] += 1
                if call_count[work_id] == 1:
                    return {
                        "latestKey": "ep-1",
                        "episodeTitle": "第1話",
                        "url": f"https://example.com/{work_id}/1",
                    }
                if work_id == "work-a":
                    return {
                        "latestKey": "ep-2",
                        "episodeTitle": "第2話",
                        "url": "https://example.com/work-a/2",
                    }
                if work_id == "work-b":
                    raise SourceParseError("parse failed")
                raise RuntimeError("request timed out")

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": state_path}, clear=False):
                with mock.patch("manga_watch.check.normalize_item", side_effect=fake_normalize):
                    with mock.patch("manga_watch.check.compute_latest", side_effect=fake_latest):
                        check.run_check(urls_path)
                        result = check.run_check(urls_path)

            self.assertEqual(1, len(result["updates"]))
            self.assertEqual("work-a", result["updates"][0]["id"])
            self.assertEqual("ep-1", result["updates"][0]["from"]["latestKey"])
            self.assertEqual("ep-2", result["updates"][0]["to"]["latestKey"])
            self.assertEqual([], result["errors"]["run"])
            self.assertEqual(
                [
                    {
                        "url": urls[1],
                        "phase": "fetch_latest",
                        "kind": "parse",
                        "errorType": "SourceParseError",
                        "message": "parse failed",
                        "id": "work-b",
                    },
                    {
                        "url": urls[2],
                        "phase": "fetch_latest",
                        "kind": "runtime",
                        "errorType": "RuntimeError",
                        "message": "request timed out",
                        "id": "work-c",
                    },
                ],
                result["errors"]["sources"],
            )

            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.assertEqual("ep-2", state["items"]["work-a"]["latest"]["latestKey"])
            self.assertEqual("ep-1", state["items"]["work-b"]["latest"]["latestKey"])
            self.assertEqual("ep-1", state["items"]["work-c"]["latest"]["latestKey"])

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
            self.assertEqual({"sources": [], "run": []}, result["errors"])

            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.assertEqual("ep-2", state["items"]["work-1"]["latest"]["latestKey"])


if __name__ == "__main__":
    unittest.main()
