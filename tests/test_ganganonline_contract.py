import json
import unittest
from pathlib import Path
from urllib.parse import urljoin


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "ganganonline" / "contract"
ORIGIN = "https://www.ganganonline.com"


def load_fixture(name: str):
    return json.loads((FIXTURES_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def candidate_work_id(payload):
    return f"ganganonline:{payload['titleId']}"


def candidate_latest_key(payload):
    for chapter in payload["chapters"]:
        if "appLaunchUrl" in chapter:
            continue
        return f"{ORIGIN}/title/{payload['titleId']}/chapter/{chapter['id']}"
    return None


def normalize_seed_from_chapter(payload):
    return urljoin(ORIGIN, payload["titleDetailUrl"])


class GanganonlineContractTests(unittest.TestCase):
    maxDiff = None

    def test_title_page_supports_canonical_seed_and_latest_public_chapter_detection(self):
        payload = load_fixture("2250-title")

        self.assertEqual(payload["inputUrl"], payload["canonicalUrl"])
        self.assertEqual("ganganonline:2250", candidate_work_id(payload))
        self.assertEqual("次回更新：4月15日", payload["chapters"][0]["mainText"])
        self.assertIn("app_info", payload["chapters"][0]["appLaunchUrl"])
        self.assertEqual(
            "https://www.ganganonline.com/title/2250/chapter/121212",
            candidate_latest_key(payload),
        )
        self.assertEqual(121212, payload["chapters"][1]["id"])
        self.assertEqual("2026.04.08〜2026.04.14", payload["chapters"][1]["publishingPeriod"])
        self.assertTrue(payload["chapters"][1]["isUpdated"])

    def test_chapter_page_normalizes_back_to_title_seed(self):
        payload = load_fixture("2250-chapter-121212")

        self.assertEqual(
            "https://www.ganganonline.com/title/2250/chapter/121212",
            payload["inputUrl"],
        )
        self.assertEqual("https://www.ganganonline.com/title/2250", normalize_seed_from_chapter(payload))
        self.assertEqual("十戒", payload["titleName"])
        self.assertEqual("9.-2", payload["chapterName"])
        self.assertEqual("https://www.ganganonline.com/share/2250/121212", payload["shareUrl"])
        self.assertGreaterEqual(payload["pagesCount"], 10)

    def test_latest_selector_skips_app_routed_cards_even_when_app_launch_url_is_empty(self):
        payload = {
            "titleId": 2250,
            "chapters": [
                {"id": 999001, "mainText": "次回更新", "appLaunchUrl": ""},
                {"id": 121212, "mainText": "9.-2"},
            ],
        }

        self.assertEqual(
            "https://www.ganganonline.com/title/2250/chapter/121212",
            candidate_latest_key(payload),
        )


if __name__ == "__main__":
    unittest.main()
