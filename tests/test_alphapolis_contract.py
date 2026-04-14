import json
import unittest
from pathlib import Path


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "alphapolis" / "contract"
ORIGIN = "https://www.alphapolis.co.jp"


def load_fixture(name: str):
    return json.loads((FIXTURES_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def candidate_work_id(payload):
    return f"alphapolis:{payload['inlinePayload']['mangaId']}"


def candidate_latest_key(payload):
    episodes = payload["inlinePayload"]["episodes"]
    if not episodes:
        return None
    return f"{ORIGIN}{episodes[-1]['url']}"


class AlphapolisContractTests(unittest.TestCase):
    maxDiff = None

    def test_active_title_page_supports_canonical_seed_and_latest_episode_detection(self):
        payload = load_fixture("208000499")

        self.assertEqual(payload["inputUrl"], payload["canonicalUrl"])
        self.assertEqual("alphapolis:208000499", candidate_work_id(payload))
        self.assertEqual("毎月第３月曜日更新", payload["scheduleLabel"])
        self.assertEqual("2026.04.27", payload["nextUpdateLabel"])
        self.assertEqual(
            "https://www.alphapolis.co.jp/manga/official/208000499/11676",
            candidate_latest_key(payload),
        )
        self.assertEqual(11676, payload["inlinePayload"]["episodes"][-1]["episodeNo"])
        self.assertEqual("2026.04.06更新", payload["inlinePayload"]["episodes"][-1]["upTime"])

    def test_prepublication_title_page_is_normalizable_but_has_no_latest_key_yet(self):
        payload = load_fixture("920000640")

        self.assertEqual(payload["inputUrl"], payload["canonicalUrl"])
        self.assertEqual("alphapolis:920000640", candidate_work_id(payload))
        self.assertEqual("毎月第2金曜日更新", payload["scheduleLabel"])
        self.assertEqual("2026.04.10公開予定", payload["prepublicationLabel"])
        self.assertTrue(payload["firstEpisodeButtonDisabled"])
        self.assertEqual([], payload["inlinePayload"]["episodes"])
        self.assertIsNone(candidate_latest_key(payload))


if __name__ == "__main__":
    unittest.main()
