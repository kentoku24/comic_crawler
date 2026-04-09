import unittest

from manga_watch.discord_availability import handle_availability_query


class DiscordAvailabilityTests(unittest.TestCase):
    def make_watchlist(self, works):
        return {"version": 2, "works": works}

    def make_state(self, works):
        return {
            "version": 2,
            "works": works,
            "last_run_at": 1_700_000_000,
            "notification_outbox": [],
        }

    def make_catalog(self, works):
        return {"version": 1, "works": works}

    def test_handle_availability_query_prefers_immediate_candidates(self):
        watchlist = self.make_watchlist(
            [
                {
                    "id": "comic-action:1",
                    "source": "comic-action",
                    "seed_url": "https://comic-action.com/episode/1",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
                {
                    "id": "KC_001_S",
                    "source": "comic-walker",
                    "seed_url": "https://comic-walker.com/detail/KC_001_S",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
            ]
        )
        state = self.make_state(
            {
                "comic-action:1": {
                    "latest": {
                        "source": "comic-action",
                        "series_title": "作品A",
                        "episode_title": "Episode 50",
                        "url": "https://comic-action.com/episode/50",
                    },
                    "history": [],
                    "unread": {"event_ids": []},
                    "health": {"consecutive_failures": 0},
                },
                "KC_001_S": {
                    "latest": {
                        "source": "comic-walker",
                        "series_title": "作品A",
                        "episode_title": "第48話 後編",
                        "url": "https://comic-walker.com/detail/KC_001_S/episodes/KC_48_E",
                        "next_update_label": "4月3日",
                    },
                    "history": [],
                    "unread": {"event_ids": []},
                    "health": {"consecutive_failures": 0},
                },
            }
        )
        catalog = self.make_catalog(
            [
                {
                    "id": "work-a",
                    "title": "作品A",
                    "aliases": ["作品A"],
                    "provider_work_ids": ["comic-action:1", "KC_001_S"],
                    "provider_candidates": [],
                }
            ]
        )

        response = handle_availability_query(
            "where 作品A / 第49話",
            watchlist_loader=lambda _: watchlist,
            state_loader=lambda _: state,
            catalog_loader=lambda _: catalog,
        )

        self.assertIsNotNone(response)
        self.assertIn("作品: 作品A", response)
        self.assertIn("目標話: 第49話", response)
        self.assertIn("結論: 今すぐ無料で読める候補があります", response)
        self.assertIn("今すぐ無料で読める候補:", response)
        self.assertIn("comic-action", response)
        self.assertIn("第50話", response)
        self.assertIn("comic-walker: あと1話不足", response)

    def test_handle_availability_query_returns_shortest_wait_candidate_when_no_immediate_option(self):
        watchlist = self.make_watchlist(
            [
                {
                    "id": "comic-action:1",
                    "source": "comic-action",
                    "seed_url": "https://comic-action.com/episode/1",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
                {
                    "id": "KC_001_S",
                    "source": "comic-walker",
                    "seed_url": "https://comic-walker.com/detail/KC_001_S",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
            ]
        )
        state = self.make_state(
            {
                "comic-action:1": {
                    "latest": {
                        "source": "comic-action",
                        "series_title": "作品A",
                        "episode_title": "第48話",
                        "url": "https://comic-action.com/episode/48",
                        "next_update_label": "4月3日",
                    },
                    "history": [],
                    "unread": {"event_ids": []},
                    "health": {"consecutive_failures": 0},
                },
                "KC_001_S": {
                    "latest": {
                        "source": "comic-walker",
                        "series_title": "作品A",
                        "episode_title": "第47話",
                        "url": "https://comic-walker.com/detail/KC_001_S/episodes/KC_47_E",
                        "next_update_label": "未定",
                    },
                    "history": [],
                    "unread": {"event_ids": []},
                    "health": {"consecutive_failures": 0},
                },
            }
        )
        catalog = self.make_catalog(
            [
                {
                    "id": "work-a",
                    "title": "作品A",
                    "aliases": ["作品A"],
                    "provider_work_ids": ["comic-action:1", "KC_001_S"],
                    "provider_candidates": [],
                }
            ]
        )

        response = handle_availability_query(
            "where 作品A / 49",
            watchlist_loader=lambda _: watchlist,
            state_loader=lambda _: state,
            catalog_loader=lambda _: catalog,
        )

        self.assertIsNotNone(response)
        self.assertIn("結論: 今すぐ無料で読める候補はありません", response)
        self.assertIn("最短候補: comic-action", response)
        self.assertIn("あと1話不足", response)
        self.assertIn("次回更新: 4月3日", response)

    def test_handle_availability_query_reports_shortage_when_no_site_reaches_target(self):
        watchlist = self.make_watchlist(
            [
                {
                    "id": "comic-action:1",
                    "source": "comic-action",
                    "seed_url": "https://comic-action.com/episode/1",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            ]
        )
        state = self.make_state(
            {
                "comic-action:1": {
                    "latest": {
                        "source": "comic-action",
                        "series_title": "作品A",
                        "episode_title": "第48話",
                        "url": "https://comic-action.com/episode/48",
                    },
                    "history": [],
                    "unread": {"event_ids": []},
                    "health": {"consecutive_failures": 0},
                }
            }
        )
        catalog = self.make_catalog(
            [
                {
                    "id": "work-a",
                    "title": "作品A",
                    "aliases": ["作品A"],
                    "provider_work_ids": ["comic-action:1"],
                    "provider_candidates": [],
                }
            ]
        )

        response = handle_availability_query(
            "where 作品A / 第50話",
            watchlist_loader=lambda _: watchlist,
            state_loader=lambda _: state,
            catalog_loader=lambda _: catalog,
        )

        self.assertIsNotNone(response)
        self.assertIn("結論: 目標話にはまだ届いていません", response)
        self.assertIn("最短でもあと2話不足", response)

    def test_handle_availability_query_ignores_unconfirmed_candidates(self):
        watchlist = self.make_watchlist(
            [
                {
                    "id": "confirmed-work",
                    "source": "comic-action",
                    "seed_url": "https://comic-action.com/episode/1",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
                {
                    "id": "candidate-work",
                    "source": "comic-walker",
                    "seed_url": "https://comic-walker.com/detail/KC_001_S",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
            ]
        )
        state = self.make_state(
            {
                "confirmed-work": {
                    "latest": {
                        "source": "comic-action",
                        "series_title": "作品A",
                        "episode_title": "第48話",
                        "url": "https://comic-action.com/episode/48",
                    },
                    "history": [],
                    "unread": {"event_ids": []},
                    "health": {"consecutive_failures": 0},
                },
                "candidate-work": {
                    "latest": {
                        "source": "comic-walker",
                        "series_title": "作品A",
                        "episode_title": "第52話",
                        "url": "https://comic-walker.com/detail/KC_001_S/episodes/KC_52_E",
                    },
                    "history": [],
                    "unread": {"event_ids": []},
                    "health": {"consecutive_failures": 0},
                },
            }
        )
        catalog = self.make_catalog(
            [
                {
                    "id": "work-a",
                    "title": "作品A",
                    "aliases": ["作品A"],
                    "provider_work_ids": ["confirmed-work"],
                    "provider_candidates": [
                        {"work_id": "candidate-work", "reason": "series_title exact match"}
                    ],
                }
            ]
        )

        response = handle_availability_query(
            "where work-a / 第50話",
            watchlist_loader=lambda _: watchlist,
            state_loader=lambda _: state,
            catalog_loader=lambda _: catalog,
        )

        self.assertIsNotNone(response)
        self.assertIn("結論: 目標話にはまだ届いていません", response)
        self.assertNotIn("candidate-work", response)

    def test_handle_availability_query_marks_unknown_sources_explicitly(self):
        watchlist = self.make_watchlist(
            [
                {
                    "id": "unknown-work",
                    "source": "kakuyomu",
                    "seed_url": "https://kakuyomu.jp/works/1",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            ]
        )
        state = self.make_state(
            {
                "unknown-work": {
                    "latest": {
                        "source": "kakuyomu",
                        "series_title": "作品A",
                        "episode_title": "番外編",
                        "url": "https://kakuyomu.jp/works/1/episodes/2",
                    },
                    "history": [],
                    "unread": {"event_ids": []},
                    "health": {"consecutive_failures": 0},
                }
            }
        )
        catalog = self.make_catalog(
            [
                {
                    "id": "work-a",
                    "title": "作品A",
                    "aliases": ["作品A"],
                    "provider_work_ids": ["unknown-work"],
                    "provider_candidates": [],
                }
            ]
        )

        response = handle_availability_query(
            "where 作品A / 第3話",
            watchlist_loader=lambda _: watchlist,
            state_loader=lambda _: state,
            catalog_loader=lambda _: catalog,
        )

        self.assertIsNotNone(response)
        self.assertIn("kakuyomu: 判定不能", response)
        self.assertIn("不明なサイトがあります", response)


if __name__ == "__main__":
    unittest.main()
