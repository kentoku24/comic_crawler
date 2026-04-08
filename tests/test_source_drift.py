import io
import json
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.source_drift import (
    CanaryObservation,
    DEFAULT_SOURCE_CANARY_CONTRACTS,
    SourceCanaryResult,
    main,
    run_source_canary,
)
from manga_watch.sources.comic_action import extract_comic_action_series_id
from manga_watch.sources.comic_earthstar import parse_comic_earthstar_title
from manga_watch.sources.comic_trail import extract_comic_trail_series_id, parse_comic_trail_title
from manga_watch.sources.comicborder import parse_comicborder_title
from manga_watch.sources.kuragebunch import parse_kuragebunch_title
from manga_watch.sources.shonenjumpplus import parse_shonenjumpplus_title
from manga_watch.sources.sunday_webry import parse_sunday_webry_title
from manga_watch.sources import registered_sources

FIXTURES_ROOT = Path(__file__).parent / "fixtures"


class FixtureHttpClient:
    def __init__(self, case_dir: Path, steps):
        self.case_dir = case_dir
        self.steps = steps
        self.index = 0

    def get_text(self, url: str) -> str:
        if self.index >= len(self.steps):
            raise AssertionError(f"{self.case_dir}: unexpected request after bundle exhausted: {url!r}")

        step = self.steps[self.index]
        self.index += 1
        expected_url = step["url"]
        if url != expected_url:
            raise AssertionError(
                f"{self.case_dir}: request #{self.index} expected {expected_url!r}, got {url!r}"
            )
        return step["body"]


def load_fixture_http_client(source: str, case_name: str):
    case_dir = FIXTURES_ROOT / source / case_name
    manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    steps = [
        {
            "url": step["url"],
            "body": (case_dir / step["response"]).read_text(encoding="utf-8"),
        }
        for step in manifest["steps"]
    ]
    return manifest, FixtureHttpClient(case_dir, steps)


class SourceDriftTests(unittest.TestCase):
    def test_default_contracts_cover_registered_sources(self):
        self.assertEqual(set(registered_sources()), set(DEFAULT_SOURCE_CANARY_CONTRACTS))

    def test_canaries_pass_on_normal_fixtures(self):
        for source in registered_sources():
            with self.subTest(source=source):
                manifest, client = load_fixture_http_client(source, "normal")
                contract = DEFAULT_SOURCE_CANARY_CONTRACTS[source]
                contract = contract.__class__(
                    source=contract.source,
                    seed_url=manifest["seedUrl"],
                    fixture_bundle=contract.fixture_bundle,
                    monitored_signals=contract.monitored_signals,
                )

                result = run_source_canary(contract, http_client=client)

                self.assertEqual("ok", result.status)
                self.assertEqual(self._expected_checked_urls(source, manifest), result.checked_urls)
                self.assertEqual(
                    self._expected_observations(source, manifest, client),
                    result.observations,
                )

    def test_broken_fixture_reports_drift_with_refresh_hint(self):
        manifest, client = load_fixture_http_client("comic-walker", "broken_missing_next_data")
        contract = DEFAULT_SOURCE_CANARY_CONTRACTS["comic-walker"]
        contract = contract.__class__(
            source=contract.source,
            seed_url=manifest["seedUrl"],
            fixture_bundle=contract.fixture_bundle,
            monitored_signals=contract.monitored_signals,
        )

        result = run_source_canary(contract, http_client=client)

        self.assertEqual("drift", result.status)
        self.assertEqual("SourceParseError", result.error_type)
        self.assertIn("__NEXT_DATA__ not found", result.message)
        self.assertIn("tests/fixtures/comic-walker/normal", result.next_action)
        self.assertIn(
            ".venv/bin/python -m unittest tests.test_source_drift tests.test_sources tests.test_check",
            result.next_action,
        )

    def test_main_returns_non_zero_when_a_canary_fails(self):
        failing_result = SourceCanaryResult(
            source="comic-walker",
            status="drift",
            seed_url="https://example.com/work",
            checked_urls=(),
            fixture_bundle="tests/fixtures/comic-walker/normal",
            monitored_signals=("series page keeps __NEXT_DATA__",),
            observations=(),
            next_action="Refresh tests/fixtures/comic-walker/normal.",
            error_type="RuntimeError",
            message="boom",
        )

        with mock.patch("manga_watch.source_drift.run_source_canaries", return_value=[failing_result]):
            with mock.patch("sys.stdout", new=io.StringIO()):
                exit_code = main(["--source", "comic-walker", "--format", "json"])

        self.assertEqual(1, exit_code)

    def _expected_checked_urls(self, source: str, manifest) -> tuple[str, ...]:
        if source == "takecomic":
            return (manifest["seedUrl"], manifest["steps"][0]["url"])
        if source == "nicovideo-manga":
            return (
                manifest["steps"][0]["url"],
                manifest["expectedLatest"]["url"],
            )
        return tuple(step["url"] for step in manifest["steps"])

    def _expected_observations(self, source: str, manifest, client: FixtureHttpClient):
        expected_latest = manifest["expectedLatest"]
        expected_work = manifest["expectedWork"]

        if source == "comic-walker":
            return (
                CanaryObservation("series_page_signal", "__NEXT_DATA__"),
                CanaryObservation("latest_episode_code", expected_latest["episodeCode"]),
                CanaryObservation("latest_episode_title", expected_latest["episodeTitle"]),
            )
        if source == "comic-action":
            series_id = extract_comic_action_series_id(client.steps[0]["body"])
            return (
                CanaryObservation("series_id", series_id or ""),
                CanaryObservation("next_readable_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", expected_latest["episodeTitle"]),
            )
        if source == "comic-earthstar":
            parsed_episode_title, parsed_series_title = parse_comic_earthstar_title(
                expected_latest["pageTitle"]
            )
            return (
                CanaryObservation("series_id", expected_work["seriesId"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", parsed_episode_title or ""),
                CanaryObservation("series_title", parsed_series_title or ""),
            )
        if source == "comicborder":
            parsed_episode_title, parsed_series_title = parse_comicborder_title(expected_latest["pageTitle"])
            return (
                CanaryObservation("series_id", expected_work["seriesId"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", parsed_episode_title or ""),
                CanaryObservation("series_title", parsed_series_title or ""),
            )
        if source == "comic-trail":
            parsed_episode_title, parsed_series_title = parse_comic_trail_title(expected_latest["pageTitle"])
            return (
                CanaryObservation(
                    "series_id",
                    extract_comic_trail_series_id(client.steps[0]["body"]) or "",
                ),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", parsed_episode_title or ""),
                CanaryObservation("series_title", parsed_series_title or ""),
            )
        if source == "kuragebunch":
            parsed_episode_title, parsed_series_title = parse_kuragebunch_title(expected_latest["pageTitle"])
            return (
                CanaryObservation("series_id", expected_work["seriesId"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", parsed_episode_title or ""),
                CanaryObservation("series_title", parsed_series_title or ""),
            )
        if source == "shonenjumpplus":
            parsed_episode_title, parsed_series_title = parse_shonenjumpplus_title(
                expected_latest["pageTitle"]
            )
            return (
                CanaryObservation("series_id", expected_work["seriesId"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", parsed_episode_title or ""),
                CanaryObservation("series_title", parsed_series_title or ""),
            )
        if source == "sunday-webry":
            parsed_episode_title, parsed_series_title = parse_sunday_webry_title(
                expected_latest["pageTitle"]
            )
            return (
                CanaryObservation("series_id", expected_work["seriesId"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", parsed_episode_title or ""),
                CanaryObservation("series_title", parsed_series_title or ""),
            )
        if source == "champion-cross":
            return (
                CanaryObservation("series_hash", expected_latest["series"].split(":", 1)[1]),
                CanaryObservation("series_title", expected_latest["seriesTitle"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", expected_latest["episodeTitle"]),
            )
        if source == "magapoke":
            return (
                CanaryObservation("rss_url", manifest["steps"][1]["url"]),
                CanaryObservation("next_update_label", expected_latest["nextUpdateLabel"]),
                CanaryObservation("series_title", expected_latest["seriesTitle"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", expected_latest["episodeTitle"]),
            )
        if source == "firecross":
            return (
                CanaryObservation("series_id", expected_latest["series"].split(":", 1)[1]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", expected_latest["episodeTitle"]),
            )
        if source == "kakuyomu":
            return (
                CanaryObservation("work_page_signal", "__NEXT_DATA__"),
                CanaryObservation("latest_episode_id", expected_latest["episodeCode"]),
                CanaryObservation("latest_episode_title", expected_latest["episodeTitle"]),
            )
        if source == "takecomic":
            return (
                CanaryObservation("series_hash", expected_work["seriesHash"]),
                CanaryObservation("series_title", expected_latest["seriesTitle"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", expected_latest["episodeTitle"]),
            )
        if source == "nicovideo-manga":
            return (
                CanaryObservation("canonical_seed_url", expected_work["seedUrl"]),
                CanaryObservation("latest_episode_url", expected_latest["url"]),
                CanaryObservation("latest_episode_title", expected_latest["episodeTitle"]),
            )
        raise AssertionError(f"unexpected source: {source}")


if __name__ == "__main__":
    unittest.main()
