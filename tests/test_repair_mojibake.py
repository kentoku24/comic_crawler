import copy
import unittest

from manga_watch.repair_mojibake import repair_mojibake, repair_state

CLEAN_TITLE = "科学的に存在しうるクリーチャー娘の観察日誌"


def garbled(text: str) -> str:
    """Deterministic construction of a Latin-1 rendered UTF-8 string.

    Hand-typed mojibake literals lose the invisible control chars (U+0080-U+009F)
    and break the latin-1 round-trip, so tests always build input this way.
    """
    return text.encode("utf-8").decode("latin-1")


class RepairMojibakeHeuristicTests(unittest.TestCase):
    maxDiff = None

    def test_garbled_title_round_trips_to_clean_title(self):
        self.assertEqual(repair_mojibake(garbled(CLEAN_TITLE)), CLEAN_TITLE)

    def test_clean_japanese_unchanged(self):
        self.assertEqual(repair_mojibake(CLEAN_TITLE), CLEAN_TITLE)

    def test_ascii_url_unchanged(self):
        url = "https://championcross.jp/episodes/939a4960ab2ce"
        self.assertEqual(repair_mojibake(url), url)

    def test_accented_european_unchanged(self):
        self.assertEqual(repair_mojibake("café"), "café")

    def test_mixed_string_with_clean_japanese_unchanged(self):
        mixed = "新着エピソードを検知しました（2026-08-11）" + garbled(CLEAN_TITLE)
        self.assertEqual(repair_mojibake(mixed), mixed)

    def test_non_str_input_unchanged(self):
        self.assertIs(repair_mojibake(None), None)
        self.assertEqual(repair_mojibake(123), 123)


def build_state():
    return {
        "version": 2,
        "works": {
            "champion-cross:6504eab816435": {
                "latest": {
                    "series_title": garbled(CLEAN_TITLE),
                    "episode_title": garbled("第112話　ノソイ4"),
                    "url": "https://championcross.jp/episodes/939a4960ab2ce",
                },
                "history": [
                    {
                        "event_id": "ev-2",
                        "seen_at": 1700000000,
                        "latest": {
                            "series_title": garbled(CLEAN_TITLE),
                            "episode_title": garbled("第112話　ノソイ4"),
                            "url": "https://championcross.jp/episodes/939a4960ab2ce",
                        },
                        "gap": {
                            "from_latest": {
                                "series_title": garbled(CLEAN_TITLE),
                                "episode_title": garbled("第111話　ノソイ3"),
                                "url": "https://championcross.jp/episodes/939a4960ab1ce",
                            },
                            "estimated_new_episode_count": 1,
                        },
                    },
                ],
                "unread": {"event_ids": ["ev-2"]},
                "health": {
                    "last_checked_at": 1700000000,
                    "last_success_at": 1700000000,
                    "consecutive_failures": 0,
                },
            },
        },
        "notification_outbox": [
            {
                "event_id": "ev-2",
                "series_title": garbled(CLEAN_TITLE),
                "url": "https://championcross.jp/episodes/939a4960ab2ce",
            },
        ],
    }


EXPECTED_REPORT_PATHS = {
    "works.champion-cross:6504eab816435.latest.series_title",
    "works.champion-cross:6504eab816435.latest.episode_title",
    "works.champion-cross:6504eab816435.history.0.latest.series_title",
    "works.champion-cross:6504eab816435.history.0.latest.episode_title",
    "works.champion-cross:6504eab816435.history.0.gap.from_latest.series_title",
    "works.champion-cross:6504eab816435.history.0.gap.from_latest.episode_title",
    "notification_outbox.0.series_title",
}


class RepairStateTests(unittest.TestCase):
    maxDiff = None

    def test_repairs_only_garbled_fields_with_correct_paths(self):
        state = build_state()
        original = copy.deepcopy(state)
        result, report = repair_state(state)

        self.assertEqual({entry["path"] for entry in report}, EXPECTED_REPORT_PATHS)
        self.assertEqual(len(report), 7)

        series_entry = next(
            entry
            for entry in report
            if entry["path"] == "works.champion-cross:6504eab816435.latest.series_title"
        )
        self.assertEqual(series_entry["from"], garbled(CLEAN_TITLE))
        self.assertEqual(series_entry["to"], CLEAN_TITLE)

        work_id = "champion-cross:6504eab816435"
        works = result["works"]
        self.assertEqual(works[work_id]["latest"]["series_title"], CLEAN_TITLE)
        self.assertEqual(works[work_id]["latest"]["episode_title"], "第112話　ノソイ4")
        self.assertEqual(
            works[work_id]["latest"]["url"],
            "https://championcross.jp/episodes/939a4960ab2ce",
        )
        self.assertEqual(
            works[work_id]["history"][0]["latest"]["episode_title"],
            "第112話　ノソイ4",
        )
        self.assertEqual(
            works[work_id]["history"][0]["gap"]["from_latest"]["series_title"],
            CLEAN_TITLE,
        )
        self.assertEqual(
            works[work_id]["history"][0]["gap"]["from_latest"]["episode_title"],
            "第111話　ノソイ3",
        )
        self.assertEqual(
            result["notification_outbox"][0]["series_title"], CLEAN_TITLE
        )

        self.assertEqual(state, original)

    def test_clean_state_untouched(self):
        state = {
            "version": 2,
            "works": {
                "w1": {
                    "latest": {
                        "series_title": CLEAN_TITLE,
                        "url": "https://example.com/1",
                    }
                }
            },
        }
        result, report = repair_state(state)
        self.assertEqual(result, state)
        self.assertEqual(report, [])

    def test_pending_message_content_never_rewritten(self):
        state = {
            "discord_delivery": {
                "daily_notification": {
                    "pending_messages": [
                        {
                            "content": garbled(CLEAN_TITLE),
                            "series_title": garbled(CLEAN_TITLE),
                        }
                    ]
                }
            }
        }
        original = copy.deepcopy(state)
        result, report = repair_state(state)

        pending = result["discord_delivery"]["daily_notification"]["pending_messages"][0]
        self.assertEqual(pending["content"], garbled(CLEAN_TITLE))
        self.assertEqual(pending["series_title"], CLEAN_TITLE)
        self.assertEqual(
            [entry["path"] for entry in report],
            ["discord_delivery.daily_notification.pending_messages.0.series_title"],
        )
        self.assertEqual(state, original)


if __name__ == "__main__":
    unittest.main()
