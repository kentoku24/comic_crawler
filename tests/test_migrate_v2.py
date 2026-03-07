import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.migrate_v2 import migrate_state_v1_to_v2, migrate_watchlist_v1_to_v2


class MigrationTests(unittest.TestCase):
    maxDiff = None

    def test_migrate_watchlist_v1_to_v2_normalizes_entries(self):
        watchlist = migrate_watchlist_v1_to_v2(
            [
                "https://comic-walker.com/detail/KC_123456_S/episodes/KC_123456001_E?episodeType=latest",
                "https://kakuyomu.jp/works/123/episodes/456",
            ]
        )

        self.assertEqual(2, watchlist["version"])
        self.assertEqual("KC_123456_S", watchlist["works"][0]["id"])
        self.assertEqual("comic-walker", watchlist["works"][0]["source"])
        self.assertEqual("kakuyomu:123", watchlist["works"][1]["id"])
        self.assertEqual(
            {"mode": "all", "allowed_update_types": None},
            watchlist["works"][1]["notification_policy"],
        )

    def test_migrate_watchlist_v1_to_v2_uses_stable_comic_action_id(self):
        fake_client = mock.Mock()
        fake_client.get_text.return_value = (
            '<div data-gtm="{&quot;episode&quot;:{&quot;series_id&quot;:&quot;13933686331663374228&quot;}}"></div>'
        )

        watchlist = migrate_watchlist_v1_to_v2(
            ["https://comic-action.com/episode/111"],
            http_client=fake_client,
        )

        self.assertEqual("comic-action:13933686331663374228", watchlist["works"][0]["id"])

    def test_migrate_state_v1_to_v2_maps_latest_and_health(self):
        watchlist = {
            "version": 2,
            "works": [
                {
                    "id": "work-1",
                    "source": "fake",
                    "seed_url": "https://example.com/work/1",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
                {
                    "id": "work-2",
                    "source": "fake",
                    "seed_url": "https://example.com/work/2",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
            ],
        }
        v1_state = {
            "version": 1,
            "items": {
                "work-1": {
                    "latest": {
                        "seriesTitle": "作品A",
                        "episodeTitle": "第1話",
                        "url": "https://example.com/work/1",
                    },
                    "seenAt": 1700000000,
                },
                "orphaned-work": {
                    "latest": {"url": "https://example.com/orphan"},
                    "seenAt": 1700000001,
                },
            },
            "lastRunAt": 1700000010,
        }

        migrated_state, orphaned = migrate_state_v1_to_v2(v1_state, watchlist)

        self.assertEqual(2, migrated_state["version"])
        self.assertEqual(1700000010, migrated_state["last_run_at"])
        self.assertEqual("work-1", migrated_state["works"]["work-1"]["latest"]["work_id"])
        self.assertEqual(
            "https://example.com/work/1",
            migrated_state["works"]["work-1"]["latest"]["latest_key"],
        )
        self.assertEqual(1700000000, migrated_state["works"]["work-1"]["health"]["last_success_at"])
        self.assertEqual({}, migrated_state["works"]["work-2"]["latest"])
        self.assertEqual(["orphaned-work"], orphaned)

    def test_migrate_state_v1_to_v2_falls_back_to_legacy_seed_url_key(self):
        watchlist = {
            "version": 2,
            "works": [
                {
                    "id": "comic-action:13933686331663374228",
                    "source": "comic-action",
                    "seed_url": "https://comic-action.com/episode/111",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            ],
        }
        v1_state = {
            "version": 1,
            "items": {
                "https://comic-action.com/episode/111": {
                    "latest": {
                        "episodeTitle": "第2話",
                        "url": "https://comic-action.com/episode/222",
                    },
                    "seenAt": 1700000000,
                }
            },
            "lastRunAt": 1700000005,
        }

        migrated_state, orphaned = migrate_state_v1_to_v2(v1_state, watchlist)

        self.assertEqual([], orphaned)
        self.assertEqual(
            "comic-action:13933686331663374228",
            migrated_state["works"]["comic-action:13933686331663374228"]["latest"]["work_id"],
        )
        self.assertEqual(
            "https://comic-action.com/episode/222",
            migrated_state["works"]["comic-action:13933686331663374228"]["latest"]["latest_key"],
        )

    def test_migration_cli_writes_backups_and_v2_outputs(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            urls_v1 = tmpdir_path / "urls.txt"
            state_v1 = tmpdir_path / "state.json"
            watchlist_v2 = tmpdir_path / "watchlist.json"
            state_v2 = tmpdir_path / "state-v2.json"
            backup_dir = tmpdir_path / "backups"

            urls_v1.write_text(
                "https://kakuyomu.jp/works/123/episodes/456\n",
                encoding="utf-8",
            )
            state_v1.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "items": {
                            "kakuyomu:123": {
                                "latest": {
                                    "episodeCode": "789",
                                    "episodeTitle": "第2話",
                                    "url": "https://kakuyomu.jp/works/123/episodes/789",
                                },
                                "seenAt": 1700000000,
                            }
                        },
                        "lastRunAt": 1700000005,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "manga_watch.migrate_v2",
                    "--watchlist-v1",
                    str(urls_v1),
                    "--state-v1",
                    str(state_v1),
                    "--watchlist-v2",
                    str(watchlist_v2),
                    "--state-v2",
                    str(state_v2),
                    "--backup-dir",
                    str(backup_dir),
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, msg=result.stderr)
            payload = json.loads(result.stdout)
            migrated_watchlist = json.loads(watchlist_v2.read_text(encoding="utf-8"))
            migrated_state = json.loads(state_v2.read_text(encoding="utf-8"))

            self.assertEqual(str(watchlist_v2), payload["watchlist_v2"])
            self.assertEqual(str(state_v2), payload["state_v2"])
            self.assertEqual(1, payload["migrated_work_count"])
            self.assertTrue((backup_dir / "urls.txt").exists())
            self.assertTrue((backup_dir / "state.json").exists())
            self.assertEqual("kakuyomu:123", migrated_watchlist["works"][0]["id"])
            self.assertEqual("789", migrated_state["works"]["kakuyomu:123"]["latest"]["latest_key"])


if __name__ == "__main__":
    unittest.main()
