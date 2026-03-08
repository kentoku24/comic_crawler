import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def write_state(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_watchlist(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class BacklogTests(unittest.TestCase):
    maxDiff = None

    def run_backlog_module(self, *args):
        repo_root = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [sys.executable, "-m", "manga_watch.backlog", *args],
            cwd=repo_root,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_backlog_module_reports_unread_and_recent_history_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            write_state(
                state_path,
                {
                    "version": 2,
                    "works": {
                        "work-1": {
                            "latest": {
                                "series_title": "作品A",
                                "episode_title": "第3話",
                                "latest_key": "ep-3",
                            },
                            "history": [
                                {
                                    "event_id": "ep-2",
                                    "seen_at": 1700000000,
                                    "latest": {
                                        "series_title": "作品A",
                                        "episode_title": "第2話",
                                        "latest_key": "ep-2",
                                    },
                                },
                                {
                                    "event_id": "ep-3",
                                    "seen_at": 1700000100,
                                    "latest": {
                                        "series_title": "作品A",
                                        "episode_title": "第3話",
                                        "latest_key": "ep-3",
                                    },
                                },
                            ],
                            "unread": {"event_ids": ["ep-3"]},
                            "health": {
                                "last_checked_at": 1700000100,
                                "last_success_at": 1700000100,
                                "consecutive_failures": 0,
                            },
                        },
                        "work-2": {
                            "latest": {
                                "series_title": "作品B",
                                "episode_title": "第1話",
                                "latest_key": "ep-1",
                            },
                            "history": [],
                            "unread": {"event_ids": []},
                            "health": {
                                "last_checked_at": 1700000200,
                                "last_success_at": 1700000200,
                                "consecutive_failures": 0,
                            },
                        }
                    },
                    "last_run_at": 1700000100,
                },
            )

            result = self.run_backlog_module(
                "--state",
                str(state_path),
                "--json",
                "--limit",
                "5",
                "--unread-only",
            )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(1, payload["unread_work_count"])
        self.assertEqual(1, payload["unread_event_count"])
        self.assertEqual(1, len(payload["works"]))
        self.assertEqual("work-1", payload["works"][0]["work_id"])
        self.assertEqual("第3話", payload["works"][0]["latest_label"])
        self.assertEqual("ep-3", payload["works"][0]["unread_events"][0]["event_id"])

    def test_backlog_module_mark_read_all_clears_unread_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            write_state(
                state_path,
                {
                    "version": 2,
                    "works": {
                        "work-1": {
                            "latest": {"episode_title": "第2話", "latest_key": "ep-2"},
                            "history": [
                                {
                                    "event_id": "ep-2",
                                    "seen_at": 1700000000,
                                    "latest": {"episode_title": "第2話", "latest_key": "ep-2"},
                                }
                            ],
                            "unread": {"event_ids": ["ep-2"]},
                            "health": {
                                "last_checked_at": 1700000000,
                                "last_success_at": 1700000000,
                                "consecutive_failures": 0,
                            },
                        },
                        "work-2": {
                            "latest": {"episode_title": "第5話", "latest_key": "ep-5"},
                            "history": [
                                {
                                    "event_id": "ep-5",
                                    "seen_at": 1700000100,
                                    "latest": {"episode_title": "第5話", "latest_key": "ep-5"},
                                }
                            ],
                            "unread": {"event_ids": ["ep-5"]},
                            "health": {
                                "last_checked_at": 1700000100,
                                "last_success_at": 1700000100,
                                "consecutive_failures": 0,
                            },
                        },
                    },
                    "last_run_at": 1700000100,
                },
            )

            result = self.run_backlog_module("--state", str(state_path), "--mark-read-all", "--json")
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("mark_read", payload["action"])
        self.assertEqual(2, payload["affected_work_count"])
        self.assertEqual(2, payload["cleared_event_count"])
        self.assertEqual([], saved_state["works"]["work-1"]["unread"]["event_ids"])
        self.assertEqual([], saved_state["works"]["work-2"]["unread"]["event_ids"])

    def test_backlog_module_mark_read_work_scopes_to_one_work(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            write_state(
                state_path,
                {
                    "version": 2,
                    "works": {
                        "work-1": {
                            "latest": {"episode_title": "第2話", "latest_key": "ep-2"},
                            "history": [
                                {
                                    "event_id": "ep-2",
                                    "seen_at": 1700000000,
                                    "latest": {"episode_title": "第2話", "latest_key": "ep-2"},
                                }
                            ],
                            "unread": {"event_ids": ["ep-2"]},
                            "health": {
                                "last_checked_at": 1700000000,
                                "last_success_at": 1700000000,
                                "consecutive_failures": 0,
                            },
                        },
                        "work-2": {
                            "latest": {"episode_title": "第5話", "latest_key": "ep-5"},
                            "history": [
                                {
                                    "event_id": "ep-5",
                                    "seen_at": 1700000100,
                                    "latest": {"episode_title": "第5話", "latest_key": "ep-5"},
                                }
                            ],
                            "unread": {"event_ids": ["ep-5"]},
                            "health": {
                                "last_checked_at": 1700000100,
                                "last_success_at": 1700000100,
                                "consecutive_failures": 0,
                            },
                        },
                    },
                    "last_run_at": 1700000100,
                },
            )

            result = self.run_backlog_module("--state", str(state_path), "--mark-read-work", "work-1", "--json")
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("work-1", payload["scope"])
        self.assertEqual(1, payload["affected_work_count"])
        self.assertEqual(1, payload["cleared_event_count"])
        self.assertEqual([], saved_state["works"]["work-1"]["unread"]["event_ids"])
        self.assertEqual(["ep-5"], saved_state["works"]["work-2"]["unread"]["event_ids"])

    def test_backlog_module_mark_read_trims_history_after_clearing_unread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            history = [
                {
                    "event_id": f"ep-{idx}",
                    "seen_at": 1700000000 + idx,
                    "latest": {"episode_title": f"第{idx}話", "latest_key": f"ep-{idx}"},
                }
                for idx in range(25)
            ]
            write_state(
                state_path,
                {
                    "version": 2,
                    "works": {
                        "work-1": {
                            "latest": {"episode_title": "第24話", "latest_key": "ep-24"},
                            "history": history,
                            "unread": {"event_ids": [event["event_id"] for event in history]},
                            "health": {
                                "last_checked_at": 1700000024,
                                "last_success_at": 1700000024,
                                "consecutive_failures": 0,
                            },
                        }
                    },
                    "last_run_at": 1700000024,
                },
            )

            result = self.run_backlog_module("--state", str(state_path), "--mark-read", "work-1", "--json")
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual([], saved_state["works"]["work-1"]["unread"]["event_ids"])
        self.assertEqual(20, len(saved_state["works"]["work-1"]["history"]))
        self.assertEqual("ep-5", saved_state["works"]["work-1"]["history"][0]["event_id"])
        self.assertEqual("ep-24", saved_state["works"]["work-1"]["history"][-1]["event_id"])

    def test_backlog_module_mark_read_uses_watchlist_history_retention(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            watchlist_path = Path(tmpdir) / "watchlist.json"
            history = [
                {
                    "event_id": f"ep-{idx}",
                    "seen_at": 1700000000 + idx,
                    "latest": {"episode_title": f"第{idx}話", "latest_key": f"ep-{idx}"},
                }
                for idx in range(6)
            ]
            write_state(
                state_path,
                {
                    "version": 2,
                    "works": {
                        "work-1": {
                            "latest": {"episode_title": "第5話", "latest_key": "ep-5"},
                            "history": history,
                            "unread": {"event_ids": [event["event_id"] for event in history]},
                            "health": {
                                "last_checked_at": 1700000005,
                                "last_success_at": 1700000005,
                                "consecutive_failures": 0,
                            },
                        }
                    },
                    "last_run_at": 1700000005,
                },
            )
            write_watchlist(
                watchlist_path,
                {
                    "version": 2,
                    "works": [
                        {
                            "id": "work-1",
                            "source": "fake",
                            "seed_url": "https://example.com/work-1",
                            "enabled": True,
                            "history_retention": 3,
                            "notification_policy": {"mode": "all", "allowed_update_types": None},
                        }
                    ],
                },
            )

            result = self.run_backlog_module(
                "--state",
                str(state_path),
                "--watchlist",
                str(watchlist_path),
                "--mark-read",
                "work-1",
                "--json",
            )
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual([], saved_state["works"]["work-1"]["unread"]["event_ids"])
        self.assertEqual(["ep-3", "ep-4", "ep-5"], [event["event_id"] for event in saved_state["works"]["work-1"]["history"]])


if __name__ == "__main__":
    unittest.main()
