import json
import unittest
from pathlib import Path


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "zerosumonline" / "contract"
ORIGIN = "https://zerosumonline.com"


def load_fixture(name: str):
    return json.loads((FIXTURES_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def candidate_work_id(payload):
    return f"zerosumonline:{payload['tag']}"


def candidate_latest_key_template(payload):
    return f"{ORIGIN}/episode/{payload['tag']}/chapter/<latestChapterId>"


class ZerosumonlineContractTests(unittest.TestCase):
    maxDiff = None

    def test_current_series_listing_seed_uses_works_series(self):
        payload = load_fixture("works_series")

        self.assertEqual(payload["inputUrl"], payload["canonicalUrl"])
        self.assertEqual("連載作品 | ゼロサムオンライン", payload["pageTitle"])
        self.assertEqual("https://api.zerosumonline.com/api/v1", payload["api"]["baseUrl"])
        self.assertEqual("/list", payload["api"]["listPath"])
        self.assertEqual(
            {"category": "series", "sort": "date"},
            payload["api"]["listQuery"],
        )
        self.assertEqual("/detail/<tag>", payload["routing"]["titlePathTemplate"])

    def test_detail_page_contract_supports_tag_work_id_and_latest_key_template(self):
        payload = load_fixture("detail_shinryu")

        self.assertEqual(payload["inputUrl"], payload["canonicalUrl"])
        self.assertEqual("zerosumonline:shinryu", candidate_work_id(payload))
        self.assertEqual(
            "神竜の後継者 出来損ないと二人の守護竜|ゼロサムオンライン",
            payload["pageTitle"],
        )
        self.assertEqual(
            "https://contents.zerosumonline.com/title_thumbnail/197.webp",
            payload["ogImage"],
        )
        self.assertEqual("/title", payload["api"]["titlePath"])
        self.assertEqual({"tag": "shinryu"}, payload["api"]["titleQuery"])
        self.assertEqual("latestChapterId", payload["publicSignals"]["titleField"])
        self.assertEqual("chapters", payload["publicSignals"]["titleViewField"])
        self.assertEqual(
            "https://zerosumonline.com/episode/shinryu/chapter/<latestChapterId>",
            candidate_latest_key_template(payload),
        )

    def test_bare_works_route_is_a_blocked_seed_not_the_active_listing_page(self):
        payload = load_fixture("works_root_blocked")

        self.assertEqual("https://zerosumonline.com/works", payload["inputUrl"])
        self.assertEqual("https://zerosumonline.com", payload["observedOgUrl"])
        self.assertEqual("ゼロサムオンライン", payload["pageTitle"])
        self.assertFalse(payload["acceptedAsSeriesListing"])
        self.assertIn("/works/series", payload["blocker"])


if __name__ == "__main__":
    unittest.main()
