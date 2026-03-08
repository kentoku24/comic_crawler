import io
import json
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.source_drift import (
    DEFAULT_SOURCE_CANARY_CONTRACTS,
    SourceCanaryResult,
    main,
    run_source_canary,
)
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
                self.assertTrue(result.checked_urls)
                self.assertGreaterEqual(len(result.observations), 3)

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


if __name__ == "__main__":
    unittest.main()
