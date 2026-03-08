import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import requests

from manga_watch import check
from manga_watch.sources import LatestEpisode, RequestsHttpClient, SourceAdapter, WorkDescriptor
from manga_watch.sources.base import SourceParseError
from manga_watch.storage import latest_runtime_to_storage, latest_storage_to_runtime


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


def watchlist_entry(
    *,
    work_id="work-1",
    source="fake",
    seed_url="https://example.com/work",
    enabled=True,
):
    return {
        "id": work_id,
        "source": source,
        "seed_url": seed_url,
        "enabled": enabled,
        "notification_policy": {
            "mode": "all",
            "allowed_update_types": None,
        },
    }


def write_watchlist(path: Path, works):
    path.write_text(
        json.dumps({"version": 2, "works": works}, ensure_ascii=False),
        encoding="utf-8",
    )


class FakeResponse:
    def __init__(self, *, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def close(self):
        self.closed = True


class SequenceSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TrackingSession:
    def __init__(self, tracker, *, delay=0.05):
        self.tracker = tracker
        self.delay = delay

    def get(self, url, headers=None, timeout=None):
        with self.tracker["lock"]:
            self.tracker["current"] += 1
            self.tracker["max"] = max(self.tracker["max"], self.tracker["current"])
        try:
            time.sleep(self.delay)
            return FakeResponse(text=url)
        finally:
            with self.tracker["lock"]:
                self.tracker["current"] -= 1


class CheckTests(unittest.TestCase):
    maxDiff = None

    def run_check_module(self, watchlist_path, *, extra_env=None):
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "manga_watch.check", str(watchlist_path)],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_check_module_runs_via_python_m(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(watchlist_path, [])

            result = self.run_check_module(
                watchlist_path,
                extra_env={"MANGA_WATCH_STATE": str(state_path)},
            )
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual(
            {"updates": [], "errors": {"sources": [], "run": []}},
            json.loads(result.stdout),
        )
        self.assertEqual(2, saved_state["version"])
        self.assertEqual({}, saved_state["works"])
        self.assertIsInstance(saved_state["last_run_at"], int)

    def test_check_module_reports_load_watchlist_failures_as_json(self):
        missing_watchlist_path = Path(tempfile.gettempdir()) / "comic-crawler-missing-watchlist.json"
        if missing_watchlist_path.exists():
            missing_watchlist_path.unlink()

        result = self.run_check_module(missing_watchlist_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual(
            {
                "updates": [],
                "errors": {
                    "sources": [],
                    "run": [
                        {
                            "stage": "load_watchlist",
                            "kind": "runtime",
                            "errorType": "FileNotFoundError",
                            "message": f"[Errno 2] No such file or directory: '{missing_watchlist_path}'",
                        }
                    ],
                },
            },
            json.loads(result.stdout),
        )
        self.assertEqual("", result.stderr)

    def test_check_module_reports_load_state_failures_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(watchlist_path, [])
            state_path.write_text("{broken json", encoding="utf-8")

            result = self.run_check_module(
                watchlist_path,
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
            watchlist_path = Path(tmpdir) / "watchlist.json"
            write_watchlist(watchlist_path, [])

            result = self.run_check_module(
                watchlist_path,
                extra_env={"MANGA_WATCH_STATE": "/dev/null/state.json"},
            )

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual([], payload["updates"])
        self.assertEqual([], payload["errors"]["sources"])
        self.assertEqual("save_state", payload["errors"]["run"][0]["stage"])
        self.assertEqual("FileExistsError", payload["errors"]["run"][0]["errorType"])
        self.assertEqual("", result.stderr)

    def test_check_module_reports_invalid_http_config_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(watchlist_path, [])

            result = self.run_check_module(
                watchlist_path,
                extra_env={
                    "MANGA_WATCH_STATE": str(state_path),
                    "MANGA_WATCH_HTTP_WORKERS": "0",
                },
            )

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual([], payload["updates"])
        self.assertEqual([], payload["errors"]["sources"])
        self.assertEqual("http_config", payload["errors"]["run"][0]["stage"])
        self.assertEqual("ValueError", payload["errors"]["run"][0]["errorType"])
        self.assertEqual("", result.stderr)

    def test_normalize_item_returns_work_descriptor_fields(self):
        item = check.normalize_item("https://kakuyomu.jp/works/123/episodes/456")

        self.assertEqual("kakuyomu", item["source"])
        self.assertEqual("kakuyomu:123", item["workId"])
        self.assertEqual("456", item["seedEpisodeId"])

    def test_build_watchlist_entry_defaults_notification_policy(self):
        entry = check.build_watchlist_entry("https://kakuyomu.jp/works/123/episodes/456")

        self.assertEqual("kakuyomu:123", entry["id"])
        self.assertEqual("kakuyomu", entry["source"])
        self.assertTrue(entry["enabled"])
        self.assertEqual(
            {"mode": "all", "allowed_update_types": None},
            entry["notification_policy"],
        )

    def test_build_watchlist_entry_accepts_kakuyomu_work_url(self):
        entry = check.build_watchlist_entry("https://kakuyomu.jp/works/123")

        self.assertEqual("kakuyomu:123", entry["id"])
        self.assertEqual("https://kakuyomu.jp/works/123", entry["seed_url"])

    def test_build_watchlist_entry_uses_stable_comic_action_work_id(self):
        fake_client = mock.Mock()
        fake_client.get_text.return_value = (
            '<div data-gtm="{&quot;episode&quot;:{&quot;series_id&quot;:&quot;13933686331663374228&quot;}}"></div>'
        )
        with mock.patch(
            "manga_watch.check.normalize_item",
            return_value={
                "source": "comic-action",
                "workId": "https://comic-action.com/episode/111",
                "seedUrl": "https://comic-action.com/episode/111",
            },
        ):
            entry = check.build_watchlist_entry(
                "https://comic-action.com/episode/111",
                http_client=fake_client,
            )

        self.assertEqual("comic-action:13933686331663374228", entry["id"])
        self.assertEqual("comic-action", entry["source"])

    def test_run_check_initializes_state_without_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(watchlist_path, [watchlist_entry()])

            latest = {
                "source": "fake",
                "workId": "work-1",
                "latestKey": "ep-1",
                "seriesTitle": "作品A",
                "episodeTitle": "第1話",
                "url": "https://example.com/work/1",
            }

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": str(state_path)}, clear=False):
                with mock.patch(
                    "manga_watch.check.normalize_item",
                    return_value={
                        "source": "fake",
                        "workId": "work-1",
                        "seedUrl": "https://example.com/work",
                    },
                ):
                    with mock.patch("manga_watch.check.compute_latest", return_value=latest):
                        result = check.run_check(str(watchlist_path))
                state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual([], result["updates"])
        self.assertEqual({"sources": [], "run": []}, result["errors"])
        self.assertIn("work-1", state["works"])
        self.assertEqual("ep-1", state["works"]["work-1"]["latest"]["latest_key"])
        self.assertEqual([], state["works"]["work-1"]["history"])
        self.assertEqual(0, state["works"]["work-1"]["health"]["consecutive_failures"])
        self.assertIsInstance(state["works"]["work-1"]["health"]["last_checked_at"], int)

    def test_run_check_skips_disabled_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(watchlist_path, [watchlist_entry(enabled=False)])

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": str(state_path)}, clear=False):
                result = check.run_check(str(watchlist_path))
                state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual({"updates": [], "errors": {"sources": [], "run": []}}, result)
        self.assertEqual({}, state["works"])

    def test_apply_item_transition_reports_updates_when_latest_changes(self):
        previous = {
            "latest": {
                "source": "fake",
                "work_id": "work-1",
                "latest_key": "ep-1",
                "series_title": "作品A",
                "episode_title": "第1話",
                "url": "https://example.com/work/1",
            },
            "history": [],
            "health": {
                "last_checked_at": 10,
                "last_success_at": 10,
                "consecutive_failures": 0,
            },
        }
        latest = {
            "source": "fake",
            "workId": "work-1",
            "latestKey": "ep-2",
            "seriesTitle": "作品A",
            "episodeTitle": "第2話",
            "url": "https://example.com/work/2",
            "update_type": "main_story",
            "classification_reason": "episode_title matched main-story numbering",
            "default_notify": True,
        }

        next_entry, update = check.apply_item_transition(
            "work-1",
            previous,
            latest,
            seen_at=20,
        )

        self.assertEqual("ep-2", next_entry["latest"]["latest_key"])
        self.assertEqual(20, next_entry["health"]["last_checked_at"])
        self.assertEqual(
            {
                "id": "work-1",
                "from": latest_storage_to_runtime(previous["latest"]),
                "to": latest,
                "update_type": "main_story",
                "classification_reason": "episode_title matched main-story numbering",
                "default_notify": True,
            },
            update,
        )

    def test_apply_item_transition_silently_merges_metadata_when_latest_key_is_stable(self):
        previous = {
            "latest": {
                "source": "fake",
                "work_id": "work-1",
                "latest_key": "ep-1",
                "series_title": "旧タイトル",
                "episode_title": "旧サブタイトル",
                "page_title": "",
                "url": "https://example.com/work/1",
                "summary": "",
                "update_type": "unknown",
                "classification_reason": "missing episode title",
                "default_notify": True,
            },
            "history": [],
            "health": {
                "last_checked_at": 10,
                "last_success_at": 10,
                "consecutive_failures": 0,
            },
        }
        latest = {
            "source": "fake",
            "workId": "work-1",
            "latestKey": "ep-1",
            "seriesTitle": "新タイトル",
            "episodeTitle": "新サブタイトル",
            "pageTitle": "作品A 第1話",
            "url": "https://example.com/work/1?ref=canonical",
            "summary": "補足",
            "update_type": "main_story",
            "classification_reason": "episode_title matched main-story numbering",
            "default_notify": True,
        }

        next_entry, update = check.apply_item_transition(
            "work-1",
            previous,
            latest,
            seen_at=20,
        )

        self.assertIsNone(update)
        runtime_latest = latest_storage_to_runtime(next_entry["latest"])
        self.assertEqual("新タイトル", runtime_latest["seriesTitle"])
        self.assertEqual("新サブタイトル", runtime_latest["episodeTitle"])
        self.assertEqual("作品A 第1話", runtime_latest["pageTitle"])
        self.assertEqual("補足", runtime_latest["summary"])
        self.assertEqual("https://example.com/work/1", runtime_latest["url"])
        self.assertEqual("main_story", runtime_latest["update_type"])
        self.assertEqual(
            "episode_title matched main-story numbering",
            runtime_latest["classification_reason"],
        )
        self.assertTrue(runtime_latest["default_notify"])
        self.assertEqual(20, next_entry["health"]["last_checked_at"])

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
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(watchlist_path, [watchlist_entry()])

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": str(state_path)}, clear=False):
                with mock.patch(
                    "manga_watch.check.normalize_item",
                    return_value={
                        "source": "fake",
                        "workId": "work-1",
                        "seedUrl": "https://example.com/work",
                    },
                ):
                    with mock.patch(
                        "manga_watch.check.compute_latest",
                        return_value={
                            "source": "fake",
                            "workId": "work-1",
                            "latestKey": "ep-1",
                            "url": "https://example.com/work/1",
                        },
                    ):
                        with mock.patch(
                            "manga_watch.check.save_state",
                            side_effect=OSError("disk full"),
                        ):
                            with self.assertRaises(check.CheckRunError) as ctx:
                                check.run_check(str(watchlist_path))

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
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(
                watchlist_path,
                [
                    watchlist_entry(work_id="work-a", seed_url="https://example.com/work/a"),
                    watchlist_entry(work_id="work-b", seed_url="https://example.com/work/b"),
                    watchlist_entry(work_id="work-c", seed_url="https://example.com/work/c"),
                ],
            )
            call_count = {"work-a": 0, "work-b": 0, "work-c": 0}

            def fake_normalize(url, adapters=None):
                work_id = url.rsplit("/", 1)[-1]
                return {
                    "source": "fake",
                    "workId": f"work-{work_id}",
                    "seedUrl": url,
                }

            def fake_latest(item, adapters=None, http_client=None):
                work_id = item["workId"]
                call_count[work_id] += 1
                if call_count[work_id] == 1:
                    return {
                        "source": "fake",
                        "workId": work_id,
                        "latestKey": "ep-1",
                        "episodeTitle": "第1話",
                        "url": f"https://example.com/{work_id}/1",
                    }
                if work_id == "work-a":
                    return {
                        "source": "fake",
                        "workId": work_id,
                        "latestKey": "ep-2",
                        "episodeTitle": "第2話",
                        "url": "https://example.com/work-a/2",
                    }
                if work_id == "work-b":
                    raise SourceParseError("parse failed")
                raise RuntimeError("request timed out")

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": str(state_path)}, clear=False):
                with mock.patch("manga_watch.check.normalize_item", side_effect=fake_normalize):
                    with mock.patch("manga_watch.check.compute_latest", side_effect=fake_latest):
                        check.run_check(str(watchlist_path))
                        result = check.run_check(str(watchlist_path))
                state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(1, len(result["updates"]))
        self.assertEqual("work-a", result["updates"][0]["id"])
        self.assertEqual("ep-1", result["updates"][0]["from"]["latestKey"])
        self.assertEqual("ep-2", result["updates"][0]["to"]["latestKey"])
        self.assertEqual([], result["errors"]["run"])
        self.assertEqual(
            [
                {
                    "url": "https://example.com/work/b",
                    "phase": "fetch_latest",
                    "kind": "parse",
                    "errorType": "SourceParseError",
                    "message": "parse failed",
                    "id": "work-b",
                },
                {
                    "url": "https://example.com/work/c",
                    "phase": "fetch_latest",
                    "kind": "runtime",
                    "errorType": "RuntimeError",
                    "message": "request timed out",
                    "id": "work-c",
                },
            ],
            result["errors"]["sources"],
        )
        self.assertEqual("ep-2", state["works"]["work-a"]["latest"]["latest_key"])
        self.assertEqual("ep-1", state["works"]["work-b"]["latest"]["latest_key"])
        self.assertEqual("ep-1", state["works"]["work-c"]["latest"]["latest_key"])
        self.assertEqual(1, state["works"]["work-b"]["health"]["consecutive_failures"])
        self.assertEqual(1, state["works"]["work-c"]["health"]["consecutive_failures"])

    def test_run_check_preserves_input_order_under_parallel_completion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(
                watchlist_path,
                [
                    watchlist_entry(work_id="work-a", seed_url="https://example.com/work/a"),
                    watchlist_entry(work_id="work-b", seed_url="https://example.com/work/b"),
                    watchlist_entry(work_id="work-c", seed_url="https://example.com/work/c"),
                ],
            )
            delays = {"work-a": 0.05, "work-b": 0.03, "work-c": 0.01}
            call_count = {"work-a": 0, "work-b": 0, "work-c": 0}
            http_config = check.HttpConfig(
                request_timeout=1,
                retry_count=0,
                retry_backoff=0.0,
                max_workers=3,
                max_workers_per_host=2,
            )

            def fake_normalize(url, adapters=None):
                work_id = url.rsplit("/", 1)[-1]
                return {
                    "source": "fake",
                    "workId": f"work-{work_id}",
                    "seedUrl": url,
                }

            def fake_latest(item, adapters=None, http_client=None):
                work_id = item["workId"]
                time.sleep(delays[work_id])
                call_count[work_id] += 1
                return {
                    "source": "fake",
                    "workId": work_id,
                    "latestKey": f"ep-{call_count[work_id]}",
                    "episodeTitle": f"第{call_count[work_id]}話",
                    "url": f"https://example.com/{work_id}/{call_count[work_id]}",
                }

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": str(state_path)}, clear=False):
                with mock.patch("manga_watch.check.normalize_item", side_effect=fake_normalize):
                    with mock.patch("manga_watch.check.compute_latest", side_effect=fake_latest):
                        check.run_check(str(watchlist_path), http_config=http_config)
                        result = check.run_check(str(watchlist_path), http_config=http_config)

        self.assertEqual(
            ["work-a", "work-b", "work-c"],
            [update["id"] for update in result["updates"]],
        )
        self.assertEqual({"sources": [], "run": []}, result["errors"])

    def test_requests_http_client_retries_timeouts_only_when_allowed(self):
        sleep_calls = []
        session = SequenceSession(
            [
                requests.Timeout("timed out"),
                FakeResponse(text="ok"),
            ]
        )
        client = RequestsHttpClient(
            timeout=7,
            retry_count=1,
            retry_backoff=0.25,
            max_requests_per_host=1,
            session=session,
            sleep=sleep_calls.append,
        )

        self.assertEqual("ok", client.get_text("https://example.com/work"))
        self.assertEqual(2, len(session.calls))
        self.assertEqual([0.25], sleep_calls)

    def test_requests_http_client_does_not_retry_404(self):
        sleep_calls = []
        session = SequenceSession([FakeResponse(status_code=404)])
        client = RequestsHttpClient(
            timeout=7,
            retry_count=3,
            retry_backoff=0.25,
            max_requests_per_host=1,
            session=session,
            sleep=sleep_calls.append,
        )

        with self.assertRaises(requests.HTTPError):
            client.get_text("https://example.com/missing")

        self.assertEqual(1, len(session.calls))
        self.assertEqual([], sleep_calls)

    def test_requests_http_client_limits_same_host_concurrency(self):
        tracker = {"current": 0, "max": 0, "lock": threading.Lock()}
        client = RequestsHttpClient(
            retry_count=0,
            max_requests_per_host=1,
            session_factory=lambda: TrackingSession(tracker),
        )

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(client.get_text, f"https://example.com/work/{idx}")
                for idx in range(3)
            ]
            self.assertEqual(
                [
                    "https://example.com/work/0",
                    "https://example.com/work/1",
                    "https://example.com/work/2",
                ],
                [future.result() for future in futures],
            )

        self.assertEqual(1, tracker["max"])

    def test_run_check_compares_using_latest_key_from_adapter_interface(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(watchlist_path, [watchlist_entry()])

            adapter = FakeAdapter(["ep-1", "ep-2"])

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": str(state_path)}, clear=False):
                check.run_check(str(watchlist_path), adapters=[adapter])
                result = check.run_check(str(watchlist_path), adapters=[adapter])
                state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(1, len(result["updates"]))
        self.assertEqual("ep-1", result["updates"][0]["from"]["latestKey"])
        self.assertEqual("ep-2", result["updates"][0]["to"]["latestKey"])
        self.assertEqual({"sources": [], "run": []}, result["errors"])
        self.assertEqual("ep-2", state["works"]["work-1"]["latest"]["latest_key"])

    def test_run_check_tracks_health_for_initial_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_watchlist(watchlist_path, [watchlist_entry()])

            with mock.patch.dict(os.environ, {"MANGA_WATCH_STATE": str(state_path)}, clear=False):
                with mock.patch(
                    "manga_watch.check.normalize_item",
                    return_value={
                        "source": "fake",
                        "workId": "work-1",
                        "seedUrl": "https://example.com/work",
                    },
                ):
                    with mock.patch(
                        "manga_watch.check.compute_latest",
                        side_effect=RuntimeError("request timed out"),
                    ):
                        result = check.run_check(str(watchlist_path))
                state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual([], result["updates"])
        self.assertEqual(1, len(result["errors"]["sources"]))
        self.assertEqual({}, state["works"]["work-1"]["latest"])
        self.assertEqual(1, state["works"]["work-1"]["health"]["consecutive_failures"])
        self.assertIsNone(state["works"]["work-1"]["health"]["last_success_at"])


if __name__ == "__main__":
    unittest.main()
