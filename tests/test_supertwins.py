import tempfile
import unittest
from pathlib import Path

from manga_watch.storage import load_state, save_state, validate_state
from manga_watch.supertwins import (
    add_group_members,
    clear_pending_action,
    clear_pending_search,
    create_group,
    ensure_supertwins_state,
    get_pending_action,
    get_pending_search,
    link_group_members,
    list_groups,
    list_group_members,
    prune_empty_groups,
    prune_small_groups,
    remove_group_members,
    set_pending_action,
    set_pending_search,
)


def make_state():
    return {
        "version": 2,
        "works": {},
        "last_run_at": None,
        "notification_outbox": [],
        "discord_delivery": {
            "daily_notification": {
                "delivered_latest_keys": {},
                "pending_messages": [],
            }
        },
    }


class SupertwinsTests(unittest.TestCase):
    maxDiff = None

    def test_ensure_supertwins_state_initializes_missing_container(self):
        original = make_state()

        updated = ensure_supertwins_state(original)

        self.assertNotIn("supertwins", original)
        self.assertEqual({"groups": {}}, updated["supertwins"])

    def test_ensure_supertwins_state_normalizes_existing_groups(self):
        updated = ensure_supertwins_state(
            {
                **make_state(),
                "supertwins": {
                    "groups": {
                        "group-b": {
                            "member_work_ids": [" work-2 ", "work-1", "work-2", ""],
                        },
                        "group-a": {
                            "member_work_ids": ["work-3"],
                            "label": "keep-me",
                        },
                    },
                    "note": "preserve-me",
                },
            }
        )

        self.assertEqual(
            {
                "groups": {
                    "group-a": {
                        "member_work_ids": ["work-3"],
                        "label": "keep-me",
                    },
                    "group-b": {
                        "member_work_ids": ["work-1", "work-2"],
                    },
                },
                "note": "preserve-me",
            },
            updated["supertwins"],
        )

    def test_create_group_add_members_remove_members_and_prune_groups(self):
        original = make_state()

        created = create_group(original, "group-1", ["work-2", "work-1"])
        added = add_group_members(created, "group-1", ["work-3", "work-1"])
        removed = remove_group_members(added, "group-1", ["work-1", "missing"])
        pruned = prune_empty_groups(remove_group_members(removed, "group-1", ["work-2", "work-3"]))

        self.assertNotIn("supertwins", original)
        self.assertEqual(
            {
                "groups": {
                    "group-1": {
                        "member_work_ids": ["work-1", "work-2"],
                    }
                }
            },
            created["supertwins"],
        )
        self.assertEqual(
            ["work-1", "work-2", "work-3"],
            added["supertwins"]["groups"]["group-1"]["member_work_ids"],
        )
        self.assertEqual(
            ["work-2", "work-3"],
            removed["supertwins"]["groups"]["group-1"]["member_work_ids"],
        )
        self.assertEqual({}, pruned["supertwins"]["groups"])

    def test_upsert_watchlist_entry_marks_duplicate_hidden(self):
        from manga_watch.supertwins import upsert_watchlist_entry

        watchlist = {
            "version": 2,
            "works": [
                {
                    "id": "work-1",
                    "source": "champion-cross",
                    "seed_url": "https://championcross.jp/series/abc",
                    "enabled": True,
                    "hidden": False,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            ],
        }
        result = upsert_watchlist_entry(
            watchlist,
            {
                "id": "work-1",
                "source": "champion-cross",
                "seed_url": "https://championcross.jp/series/abc",
                "enabled": True,
                "notification_policy": {"mode": "all", "allowed_update_types": None},
            },
            hidden=True,
        )

        self.assertEqual("duplicate", result["action"])
        self.assertTrue(result["watchlist"]["works"][0]["hidden"])

    def test_pending_action_round_trip_preserves_super_twins_payload(self):
        state = {
            **make_state(),
            "supertwins": {
                "groups": {},
                "pending_actions": {"stale": {"group_id": "group-1", "member_work_ids": ["work-1"]}},
            },
        }

        updated = set_pending_action(
            state,
            "token-1",
            {"group_id": "group-2", "member_work_ids": ["work-2"]},
        )

        self.assertEqual(
            {"group_id": "group-2", "member_work_ids": ["work-2"]},
            get_pending_action(updated, "token-1"),
        )
        cleared = clear_pending_action(updated, "token-1")
        self.assertNotIn("token-1", cleared["supertwins"].get("pending_actions", {}))

    def test_pending_search_round_trip_preserves_search_payload(self):
        state = {
            **make_state(),
            "supertwins": {
                "groups": {},
                "pending_searches": {"stale": {"root_work_id": "work-1", "selected_urls_by_value": {"u:x": "https://example.com"}}},
            },
        }

        updated = set_pending_search(
            state,
            "search-1",
            {
                "root_work_id": "work-2",
                "selected_urls_by_value": {"u:y": "https://example.com/2"},
            },
        )

        self.assertEqual(
            {
                "root_work_id": "work-2",
                "selected_urls_by_value": {"u:y": "https://example.com/2"},
            },
            get_pending_search(updated, "search-1"),
        )
        cleared = clear_pending_search(updated, "search-1")
        self.assertNotIn("search-1", cleared["supertwins"].get("pending_searches", {}))

    def test_list_groups_returns_stable_sorted_shape(self):
        state = {
            **make_state(),
            "supertwins": {
                "groups": {
                    "group-b": {"member_work_ids": ["work-2", "work-1"]},
                    "group-a": {"member_work_ids": ["work-3"]},
                }
            },
        }
        listed = list_groups(state)

        self.assertEqual(
            [
                {"group_id": "group-a", "member_work_ids": ["work-3"]},
                {"group_id": "group-b", "member_work_ids": ["work-1", "work-2"]},
            ],
            listed,
        )
        self.assertEqual(["work-1", "work-2"], list_group_members(state, "group-b"))

    def test_validate_state_preserves_existing_supertwins_payload(self):
        validated = validate_state(
            {
                **make_state(),
                "supertwins": {
                    "groups": {
                        "group-1": {"member_work_ids": ["work-2", "work-1"]},
                    }
                },
            }
        )

        self.assertEqual(
            {
                "groups": {
                    "group-1": {"member_work_ids": ["work-2", "work-1"]},
                }
            },
            validated["supertwins"],
        )

    def test_save_and_load_state_round_trip_supertwins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            state = create_group(make_state(), "group-1", ["work-2", "work-1"])

            save_state(state, path=str(state_path))
            loaded = load_state(str(state_path))

        self.assertEqual(state["supertwins"], loaded["supertwins"])

    def test_link_group_members_merges_existing_groups(self):
        state = {
            **make_state(),
            "supertwins": {
                "groups": {
                    "group-1": {"member_work_ids": ["work-1", "work-2"]},
                    "group-2": {"member_work_ids": ["work-3", "work-4"]},
                }
            },
        }

        updated, group_id = link_group_members(state, ["work-2", "work-3", "work-5"])

        self.assertEqual("group-1", group_id)
        self.assertEqual(
            ["work-1", "work-2", "work-3", "work-4", "work-5"],
            updated["supertwins"]["groups"]["group-1"]["member_work_ids"],
        )
        self.assertNotIn("group-2", updated["supertwins"]["groups"])

    def test_pending_action_round_trip_and_prune_small_groups(self):
        state = set_pending_action(
            create_group(make_state(), "group-1", ["work-1", "work-2"]),
            "token-1",
            {"group_id": "group-1", "member_work_ids": ["work-2"]},
        )

        self.assertEqual(
            {"group_id": "group-1", "member_work_ids": ["work-2"]},
            get_pending_action(state, "token-1"),
        )
        cleared = clear_pending_action(state, "token-1")
        pruned = prune_small_groups(remove_group_members(cleared, "group-1", ["work-2"]))

        self.assertNotIn("pending_actions", pruned["supertwins"])
        self.assertEqual({}, pruned["supertwins"]["groups"])


if __name__ == "__main__":
    unittest.main()
