import json
import unittest
from pathlib import Path


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "takecomic" / "contract"
ORIGIN = "https://takecomic.jp"


def load_fixture(name: str):
    return json.loads((FIXTURES_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def candidate_work_id(payload):
    return f"takecomic:{payload['series']['indexId']}"


def candidate_latest_key(payload):
    return f"{ORIGIN}/episodes/{payload['lastEpisode']['id']}/"


class TakecomicContractTests(unittest.TestCase):
    maxDiff = None

    def test_historical_root_redirects_to_takecomic_landing(self):
        payload = load_fixture("historical_root_redirect")

        self.assertEqual("https://mangalifewin.takeshobo.co.jp/", payload["inputUrl"])
        self.assertEqual("https://takecomic.jp/", payload["redirectChain"][0]["location"])
        self.assertEqual("https://takecomic.jp/", payload["finalUrl"])
        self.assertEqual("https://takecomic.jp", payload["finalCanonicalUrl"])
        self.assertEqual("root_landing_only", payload["mappingDecision"])

    def test_series_page_supports_canonical_seed_and_latest_episode_detection(self):
        payload = load_fixture("series_a3c3f4363f8d5")

        self.assertEqual(payload["inputUrl"], payload["canonicalUrl"])
        self.assertEqual("a3c3f4363f8d5", payload["seriesHash"])
        self.assertEqual("takecomic:15055", candidate_work_id(payload))
        self.assertEqual("水曜更新", payload["scheduleLabel"])
        self.assertEqual("https://takecomic.jp/series/a3c3f4363f8d5/rss", payload["rssUrl"])
        self.assertEqual("5話", payload["lastEpisode"]["title"])
        self.assertEqual("110db269ebfe8", payload["lastEpisode"]["id"])
        self.assertEqual("https://takecomic.jp/episodes/110db269ebfe8/", candidate_latest_key(payload))
        self.assertEqual(candidate_latest_key(payload), payload["rssLatestItem"]["normalizedLink"])


if __name__ == "__main__":
    unittest.main()
