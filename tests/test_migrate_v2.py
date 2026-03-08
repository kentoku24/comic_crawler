import json
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from manga_watch.migrate_v2 import (
    main,
    migrate_state_v1_to_v2,
    migrate_watchlist_v1_to_v2,
    validate_pre_cutover_image_ref,
)


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
        self.assertEqual([], migrated_state["works"]["work-1"]["unread"]["event_ids"])
        self.assertEqual(1700000000, migrated_state["works"]["work-1"]["health"]["last_success_at"])
        self.assertEqual({}, migrated_state["works"]["work-2"]["latest"])
        self.assertEqual([], migrated_state["works"]["work-2"]["unread"]["event_ids"])
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
        self.assertEqual(
            [],
            migrated_state["works"]["comic-action:13933686331663374228"]["unread"]["event_ids"],
        )

    def test_validate_pre_cutover_image_ref_rejects_floating_refs(self):
        with self.assertRaisesRegex(ValueError, "immutable"):
            validate_pre_cutover_image_ref("latest")

    def test_main_captures_git_commit_before_creating_backups(self):
        call_order = []

        def record_git_commit(*args, **kwargs):
            call_order.append("resolve_pre_cutover_git_commit")
            return {"ref": "0" * 40, "captured_via": "cli", "git_dirty": False}

        def record_backups(*args, **kwargs):
            call_order.append("backup_inputs")
            return [
                {
                    "kind": "watchlist_v1",
                    "source_path": "/tmp/urls.txt",
                    "backup_path": "/tmp/backups/urls.txt",
                    "restore_to_path": "/tmp/urls.txt",
                }
            ]

        with (
            mock.patch("manga_watch.migrate_v2.read_v1_urls", return_value=[]),
            mock.patch("manga_watch.migrate_v2.migrate_watchlist_v1_to_v2", return_value={"version": 2, "works": []}),
            mock.patch("manga_watch.migrate_v2.load_v1_state", return_value={"version": 1, "items": {}, "lastRunAt": None}),
            mock.patch(
                "manga_watch.migrate_v2.migrate_state_v1_to_v2",
                return_value=({"version": 2, "works": {}, "last_run_at": None}, []),
            ),
            mock.patch("manga_watch.migrate_v2.validate_pre_cutover_image_ref", return_value="sha256:" + "0" * 64),
            mock.patch(
                "manga_watch.migrate_v2.resolve_pre_cutover_git_commit",
                side_effect=record_git_commit,
            ),
            mock.patch("manga_watch.migrate_v2.backup_inputs", side_effect=record_backups),
            mock.patch(
                "manga_watch.migrate_v2.write_rollback_manifest",
                return_value="/tmp/backups/rollback-manifest.json",
            ),
            mock.patch("manga_watch.migrate_v2.atomic_write_json"),
            redirect_stdout(io.StringIO()),
        ):
            result = main(
                [
                    "--watchlist-v1",
                    "/tmp/urls.txt",
                    "--state-v1",
                    "/tmp/state.json",
                    "--watchlist-v2",
                    "/tmp/watchlist.json",
                    "--state-v2",
                    "/tmp/state-v2.json",
                    "--backup-dir",
                    "/tmp/backups",
                    "--pre-cutover-image-ref",
                    "sha256:" + "0" * 64,
                ]
            )

        self.assertEqual(0, result)
        self.assertEqual(
            ["resolve_pre_cutover_git_commit", "backup_inputs"],
            call_order,
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
            image_ref = (
                "ghcr.io/kentoku24/comic_crawler@sha256:"
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
            )
            git_commit = "0123456789abcdef0123456789abcdef01234567"

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
                    "--pre-cutover-image-ref",
                    image_ref,
                    "--pre-cutover-git-commit",
                    git_commit,
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
            rollback_manifest = json.loads(
                Path(payload["rollback_manifest_path"]).read_text(encoding="utf-8")
            )

            self.assertEqual(str(watchlist_v2), payload["watchlist_v2"])
            self.assertEqual(str(state_v2), payload["state_v2"])
            self.assertEqual(1, payload["migrated_work_count"])
            self.assertTrue((backup_dir / "urls.txt").exists())
            self.assertTrue((backup_dir / "state.json").exists())
            self.assertEqual(
                str(backup_dir / "rollback-manifest.json"),
                payload["rollback_manifest_path"],
            )
            self.assertEqual(image_ref, payload["pre_cutover_runtime"]["image_ref"])
            self.assertEqual("image_digest", payload["pre_cutover_runtime"]["image_ref_kind"])
            self.assertEqual(git_commit, payload["pre_cutover_runtime"]["git_commit"])
            self.assertEqual("kakuyomu:123", migrated_watchlist["works"][0]["id"])
            self.assertEqual("789", migrated_state["works"]["kakuyomu:123"]["latest"]["latest_key"])
            self.assertEqual([], migrated_state["works"]["kakuyomu:123"]["unread"]["event_ids"])
            self.assertEqual(1, rollback_manifest["schema_version"])
            self.assertEqual(str(backup_dir), rollback_manifest["backup_dir"])
            self.assertEqual(image_ref, rollback_manifest["pre_cutover_runtime"]["image_ref"])
            self.assertEqual("image_digest", rollback_manifest["pre_cutover_runtime"]["image_ref_kind"])
            self.assertEqual(git_commit, rollback_manifest["pre_cutover_runtime"]["git_commit"])
            self.assertEqual(
                [
                    {
                        "kind": "watchlist_v1",
                        "source_path": str(urls_v1),
                        "backup_path": str(backup_dir / "urls.txt"),
                        "restore_to_path": str(urls_v1),
                    },
                    {
                        "kind": "state_v1",
                        "source_path": str(state_v1),
                        "backup_path": str(backup_dir / "state.json"),
                        "restore_to_path": str(state_v1),
                    },
                ],
                rollback_manifest["data_backups"],
            )
            self.assertEqual(
                [
                    {"kind": "watchlist_v2", "path": str(watchlist_v2)},
                    {"kind": "state_v2", "path": str(state_v2)},
                ],
                rollback_manifest["cutover_outputs"],
            )
            self.assertEqual(3, len(rollback_manifest["rollback_prechecks"]))
            self.assertEqual(
                "python3 -m manga_watch.check " + str(urls_v1),
                rollback_manifest["rollback_smoke_checks"][0]["command"],
            )
            self.assertEqual(
                "docker compose up -d comic-crawler",
                rollback_manifest["rollback_smoke_checks"][1]["command"],
            )


if __name__ == "__main__":
    unittest.main()
