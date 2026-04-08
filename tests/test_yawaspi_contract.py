import json
import re
import unittest
from pathlib import Path
from urllib.parse import urljoin


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yawaspi" / "investigation_contract"


def _load_manifest():
    return json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


def _load_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _series_links(html: str) -> list[str]:
    links = []
    for href in re.findall(r'href="(/[^"#?]+/index\.html)"', html):
        if href not in links:
            links.append(href)
    return links


def _extract_work_entries(html: str, seed_url: str) -> list[dict[str, str]]:
    match = re.search(
        r'<section class="page__read">.*?<ul class="inner__content">(.*?)</ul>',
        html,
        re.DOTALL,
    )
    if not match:
        raise AssertionError("page__read section missing")

    entries = []
    pattern = re.compile(
        r'<li><a href="(?P<href>/[^"]+/comic/(?P<basename>[^"/]+\.html))".*?<dt>(?P<title>.*?)</dt>',
        re.DOTALL,
    )
    for entry in pattern.finditer(match.group(1)):
        title = re.sub(r"<.*?>", "", entry.group("title")).strip()
        entries.append(
            {
                "url": urljoin(seed_url, entry.group("href")),
                "basename": entry.group("basename"),
                "title": title,
            }
        )
    return entries


def _canonical_seed(html: str) -> str:
    match = re.search(r'<meta property="og:url" content="([^"]+)"', html)
    if not match:
        raise AssertionError("og:url missing")
    return match.group(1)


def _latest_story_entry(html: str, seed_url: str) -> dict[str, str]:
    for entry in _extract_work_entries(html, seed_url):
        if not entry["basename"].startswith("sp"):
            return entry
    raise AssertionError("main-story candidate missing")


class YawaspiContractTests(unittest.TestCase):
    maxDiff = None

    def test_series_catalog_exposes_work_page_links(self):
        manifest = _load_manifest()
        html = _load_text("01-series.html")

        links = _series_links(html)

        self.assertIn("/itsuwari/index.html", links)
        self.assertIn("/yakutohi/index.html", links)
        self.assertEqual(manifest["catalog_url"], "https://yawaspi.com/series/index.html")

    def test_work_pages_expose_canonical_seed_and_main_story_latest_candidate(self):
        manifest = _load_manifest()

        for case in manifest["work_pages"]:
            with self.subTest(slug=case["slug"]):
                html = _load_text(case["response"])
                seed_url = case["url"]

                self.assertEqual(case["canonical_seed"], _canonical_seed(html))
                self.assertEqual(case["expected_latest_url"], _latest_story_entry(html, seed_url)["url"])

    def test_investigation_doc_records_contract_decision(self):
        doc_path = Path(__file__).resolve().parents[1] / "doc" / "source-investigations" / "yawaspi.md"

        contents = doc_path.read_text(encoding="utf-8")

        self.assertIn("accepted input URL", contents)
        self.assertIn("canonical seed", contents)
        self.assertIn("work_id", contents)
        self.assertIn("latest_key", contents)
        self.assertIn("implementation-ready", contents)
