import unittest

from manga_watch.sources.base import LatestEpisode
from manga_watch.update_classification import (
    ANNOUNCEMENT,
    BONUS,
    UNKNOWN,
    classify_update,
)


class UpdateClassificationTests(unittest.TestCase):
    def test_source_specific_announcement_examples(self):
        cases = (
            (
                "comic-walker",
                "更新のお知らせ",
                "【更新のお知らせ】作品A｜カドコミ (コミックウォーカー)",
            ),
            (
                "comic-action",
                "休載のお知らせ",
                "休載のお知らせ / 作品B - webアクション | comic-action",
            ),
            (
                "kakuyomu",
                "次回更新のお知らせ",
                "次回更新のお知らせ - 作品C - カクヨム",
            ),
        )
        for source, episode_title, page_title in cases:
            with self.subTest(source=source):
                decision = classify_update(
                    episode_title=episode_title,
                    page_title=page_title,
                )
                self.assertEqual(ANNOUNCEMENT, decision.update_type)
                self.assertIn("announcement", decision.classification_reason)
                self.assertFalse(decision.default_notify)

    def test_conflicting_main_story_and_bonus_signals_fail_open(self):
        decision = classify_update(
            episode_title="第12話 番外編",
            page_title="第12話 番外編 - 作品C - カクヨム",
        )

        self.assertEqual(UNKNOWN, decision.update_type)
        self.assertIn("main-story markers", decision.classification_reason)
        self.assertIn("bonus markers", decision.classification_reason)
        self.assertTrue(decision.default_notify)

    def test_bonus_and_announcement_conflicts_stay_suppressed(self):
        decision = classify_update(
            episode_title="番外編のお知らせ",
            page_title="番外編のお知らせ - 作品C - カクヨム",
        )

        self.assertEqual(ANNOUNCEMENT, decision.update_type)
        self.assertIn("bonus markers", decision.classification_reason)
        self.assertIn("announcement markers", decision.classification_reason)
        self.assertIn("kept suppressed as announcement", decision.classification_reason)
        self.assertFalse(decision.default_notify)

    def test_latest_episode_to_dict_includes_classification_fields(self):
        latest = LatestEpisode(
            source="comic-action",
            work_id="https://comic-action.com/episode/333",
            latest_key="https://comic-action.com/episode/333",
            url="https://comic-action.com/episode/333",
            series_title="作品B",
            episode_title="番外編",
            page_title="番外編 / 作品B - 著者名 | comic-action",
        )

        payload = latest.to_dict()

        self.assertEqual(BONUS, payload["update_type"])
        self.assertIn("classification_reason", payload)
        self.assertTrue(payload["classification_reason"])
        self.assertFalse(payload["default_notify"])

    def test_unknown_without_strong_signal(self):
        decision = classify_update(
            episode_title="最新エピソード",
            page_title="最新エピソード｜作品A",
        )

        self.assertEqual(UNKNOWN, decision.update_type)
        self.assertEqual("no classification markers matched", decision.classification_reason)
        self.assertTrue(decision.default_notify)

    def test_piccoma_court_number_label_is_main_story(self):
        decision = classify_update(episode_title="第134審 (2)")

        self.assertEqual("main_story", decision.update_type)
        self.assertTrue(decision.default_notify)


if __name__ == "__main__":
    unittest.main()
