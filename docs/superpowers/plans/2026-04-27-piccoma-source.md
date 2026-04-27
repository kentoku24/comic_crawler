# Piccoma Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Piccoma as a supported `comic_crawler` source for public unauthenticated episode tracking, `/search`, and `/supertwins-search`.

**Architecture:** Add a focused `PiccomaAdapter` that normalizes Piccoma product URLs and extracts episode-reading latest data from public product pages. Register the adapter through the existing source registry, watchlist capability table, source drift canary, and `source_search.py` opt-in search surface so existing Discord flows pick it up without UX rewrites.

**Tech Stack:** Python stdlib (`re`, `html`, `urllib.parse`, `unittest`), existing `manga_watch` source adapter interfaces, existing fixture-based regression tests.

---

## Spec

Design spec: `docs/superpowers/specs/2026-04-27-piccoma-source-design.md`

Base: `origin/main` at `a1c591f`

## File Map

- Create `manga_watch/sources/piccoma.py`: URL canonicalization, public product-page parsing helpers, and `PiccomaAdapter`.
- Modify `manga_watch/sources/registry.py`: import and register `PiccomaAdapter`.
- Modify `manga_watch/watchlist.py`: add Piccoma to `SOURCE_CAPABILITIES`.
- Modify `manga_watch/source_search.py`: add Piccoma search config and a Piccoma-specific search parser if generic anchor extraction is too broad.
- Modify `manga_watch/source_drift.py`: import Piccoma helpers, add canary contract, canary runner, and runner map entry.
- Modify `tests/test_sources.py`: add Piccoma fixture cases, imports, registry expectation, normalize and helper tests.
- Modify `tests/test_watchlist.py`: add Piccoma `watchlist add`, duplicate, and unsupported URL type coverage.
- Modify `tests/test_source_search.py`: add Piccoma to supported source expectation and search parsing tests.
- Modify `tests/test_source_drift.py`: existing source coverage should include Piccoma once registry and canary contract are added; add targeted Piccoma canary assertions if needed.
- Modify `tests/test_source_search_e2e.py`: add optional real-network Piccoma representative case after choosing a stable query.
- Modify `README.md`: document Piccoma support and the explicit public-only / no-login / no-purchase-state scope.
- Create `tests/fixtures/piccoma/normal/manifest.json` and `01-product.html`: normal crawl fixture.
- Create `tests/fixtures/piccoma/broken_missing_episode/manifest.json` and `01-product.html`: parse-error fixture.
- Create `tests/fixtures/source-search/piccoma/01-search.html`: search fixture.

## Implementation Notes

- Do not use logged-in Piccoma data, cookies, purchase state, app-only APIs, or inferred episode URLs.
- Use canonical seed URL `https://piccoma.com/web/product/<product_id>?etype=episode`.
- Use `work_id = "piccoma:<product_id>"`.
- `LatestEpisode.url` may stay as the product URL unless a stable public episode URL is present in HTML.
- Fatal parse errors: product id missing, product page title missing, or episode-reading latest identifier missing.
- Non-fatal missing fields: free episode label, wait-free label, total episode label, individual episode URL.
- Commit after each task unless the task only probes live HTML and does not change tracked files.

### Task 1: Live Piccoma Contract Probe

**Files:**
- Read: `docs/superpowers/specs/2026-04-27-piccoma-source-design.md`
- Read: `manga_watch/source_search.py`
- Read: `manga_watch/source_drift.py`
- No tracked file edits in this task

- [ ] **Step 1: Probe a known public product page**

Run:

```bash
.venv/bin/python - <<'PY'
from manga_watch.sources.base import RequestsHttpClient
url = "https://piccoma.com/web/product/58170?etype=episode"
html = RequestsHttpClient().get_text(url)
print(url)
print(len(html))
for needle in ("九条の大罪", "話読み", "全 313 話", "待てば", "__NEXT_DATA__", "application/ld+json"):
    print(needle, needle in html)
PY
```

Expected: output confirms the page is fetchable and shows at least one stable title and episode-reading signal.

- [ ] **Step 2: Probe likely search URLs**

Run small probes against the current public site to identify the exact search endpoint.

```bash
.venv/bin/python - <<'PY'
from urllib.parse import quote_plus
from manga_watch.sources.base import RequestsHttpClient

client = RequestsHttpClient()
query = quote_plus("九条の大罪")
urls = [
    f"https://piccoma.com/web/search?word={query}",
    f"https://piccoma.com/web/search?q={query}",
    f"https://piccoma.com/web/search/result?word={query}",
    f"https://piccoma.com/web/search/result?q={query}",
]
for url in urls:
    try:
        html = client.get_text(url)
    except Exception as exc:
        print(url, type(exc).__name__, exc)
        continue
    print(url, len(html), "九条の大罪" in html, "/web/product/" in html)
PY
```

Expected: one URL gives a public HTML response with query results and `/web/product/<id>` links.

- [ ] **Step 3: Freeze parser contract notes**

Record these values in the implementation PR notes or task comments before coding:

```text
product canary URL:
search URL template:
series title signal:
episode latest signal:
episode title label:
availability labels:
stable individual episode URL present?: yes/no
```

Expected: implementation can proceed without guessing selectors.

### Task 2: Piccoma Adapter Tests First

**Files:**
- Modify: `tests/test_sources.py`
- Create: `tests/fixtures/piccoma/normal/manifest.json`
- Create: `tests/fixtures/piccoma/normal/01-product.html`
- Create: `tests/fixtures/piccoma/broken_missing_episode/manifest.json`
- Create: `tests/fixtures/piccoma/broken_missing_episode/01-product.html`

- [ ] **Step 1: Add Piccoma fixture cases**

Add to `SOURCE_CASES`:

```python
"piccoma": (
    "normal",
    "broken_missing_episode",
),
```

Add to `EXPECTED_LATEST_CLASSIFICATIONS`:

```python
"piccoma": {
    "normal": "main_story",
},
```

Add import placeholder:

```python
from manga_watch.sources.piccoma import PiccomaAdapter
```

- [ ] **Step 2: Add failing registry expectation**

Update `test_registry_pins_supported_sources` to include `piccoma` at the end of the expected tuple.

Expected tuple suffix:

```python
(
    # existing sources...
    "gaugau",
    "piccoma",
)
```

- [ ] **Step 3: Add failing normalize tests**

Add tests:

```python
def test_piccoma_normalize_accepts_product_url(self):
    work = PiccomaAdapter().normalize("https://piccoma.com/web/product/58170?etype=episode")

    self.assertEqual(
        {
            "source": "piccoma",
            "kind": "piccoma",
            "workId": "piccoma:58170",
            "seedUrl": "https://piccoma.com/web/product/58170?etype=episode",
            "series": "piccoma:58170",
            "productId": "58170",
        },
        work.to_dict(),
    )

def test_piccoma_normalize_canonicalizes_query_variants(self):
    work = PiccomaAdapter().normalize("https://piccoma.com/web/product/58170?foo=bar")

    self.assertEqual("https://piccoma.com/web/product/58170?etype=episode", work.seed_url)
```

- [ ] **Step 4: Create normal fixture**

Use sanitized HTML shaped like the live contract. Keep only parser-needed fragments.

Example fixture body if the live page exposes text-only labels:

```html
<html>
  <head><title>九条の大罪｜41話 待てば¥0｜無料漫画ならピッコマ</title></head>
  <body>
    <h1>九条の大罪</h1>
    <section data-testid="episode-tab">
      <span>話読み</span>
      <a href="/web/product/58170?etype=episode">全 313 話</a>
      <p>77話分無料</p>
      <p>41 話分</p>
      <ol>
        <li>第1審 (1) ¥0</li>
        <li>第1審 (2) ¥0</li>
        <li>第313審 待てば¥0</li>
      </ol>
    </section>
  </body>
</html>
```

`manifest.json`:

```json
{
  "seedUrl": "https://piccoma.com/web/product/58170?etype=episode",
  "work": {
    "source": "piccoma",
    "kind": "piccoma",
    "workId": "piccoma:58170",
    "seedUrl": "https://piccoma.com/web/product/58170?etype=episode",
    "series": "piccoma:58170",
    "productId": "58170"
  },
  "steps": [
    {
      "url": "https://piccoma.com/web/product/58170?etype=episode",
      "response": "01-product.html"
    }
  ],
  "latest": {
    "source": "piccoma",
    "workId": "piccoma:58170",
    "latestKey": "piccoma:58170:episode:313",
    "url": "https://piccoma.com/web/product/58170?etype=episode",
    "series": "piccoma:58170",
    "seriesTitle": "九条の大罪",
    "episodeTitle": "第313話",
    "pageTitle": "九条の大罪｜41話 待てば¥0｜無料漫画ならピッコマ",
    "update_type": "main_story",
    "classification_reason": "episode_title matched main-story numbering",
    "default_notify": true,
    "freeEpisodeLabel": "77話分無料",
    "waitFreeLabel": "41 話分",
    "totalEpisodeLabel": "全 313 話"
  }
}
```

- [ ] **Step 5: Create broken fixture**

Use product title but omit episode-reading latest signal.

`manifest.json` expected error:

```json
{
  "seedUrl": "https://piccoma.com/web/product/58170?etype=episode",
  "work": {
    "source": "piccoma",
    "kind": "piccoma",
    "workId": "piccoma:58170",
    "seedUrl": "https://piccoma.com/web/product/58170?etype=episode",
    "series": "piccoma:58170",
    "productId": "58170"
  },
  "steps": [
    {
      "url": "https://piccoma.com/web/product/58170?etype=episode",
      "response": "01-product.html"
    }
  ],
  "error": {
    "type": "SourceParseError",
    "message": "piccoma: latest episode identifier not found"
  }
}
```

- [ ] **Step 6: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_sources
```

Expected: FAIL because `manga_watch.sources.piccoma` does not exist or `piccoma` is not registered.

### Task 3: Implement Piccoma Adapter

**Files:**
- Create: `manga_watch/sources/piccoma.py`
- Modify: `manga_watch/sources/registry.py`
- Modify: `manga_watch/sources/__init__.py` only if imports need export changes; likely not needed
- Test: `tests/test_sources.py`

- [ ] **Step 1: Create adapter module**

Implement focused helpers. Start with the live-probe contract, then keep regexes permissive enough for fixtures.

Skeleton:

```python
import html
import re
from typing import Optional
from urllib.parse import urlsplit

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title

_PRODUCT_URL = re.compile(
    r"^https?://(?:www\.)?piccoma\.com/web/product/(\d+)(?:/)?(?:\?.*)?$"
)


def canonical_piccoma_product_url(product_id: str) -> str:
    return f"https://piccoma.com/web/product/{product_id}?etype=episode"


def extract_piccoma_product_id(seed_url: str) -> Optional[str]:
    match = _PRODUCT_URL.match(str(seed_url or "").strip())
    return match.group(1) if match else None


def parse_piccoma_product_url(seed_url: str) -> Optional[str]:
    product_id = extract_piccoma_product_id(seed_url)
    if not product_id:
        return None
    return canonical_piccoma_product_url(product_id)
```

- [ ] **Step 2: Implement parsing helpers**

Implement helpers that work with the fixture and live-probe signal.

Implement these helper functions in `manga_watch/sources/piccoma.py`:

```python
def _plain_text(html_text: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text or ""))).strip()


def extract_piccoma_series_title(html_text: str, page_title: Optional[str] = None) -> Optional[str]:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html_text or "", re.I | re.S)
    if match:
        title = _plain_text(match.group(1))
        if title:
            return title
    if page_title:
        title = re.split(r"[｜|]", page_title, maxsplit=1)[0].strip()
        return title or None
    return None


def extract_piccoma_total_episode_label(html_text: str) -> Optional[str]:
    text = _plain_text(html_text)
    match = re.search(r"全\s*(\d+)\s*話", text)
    return f"全 {match.group(1)} 話" if match else None


def extract_piccoma_free_episode_label(html_text: str) -> Optional[str]:
    text = _plain_text(html_text)
    match = re.search(r"(\d+\s*話分無料|\d+\s*話無料)", text)
    return re.sub(r"\s+", "", match.group(1)) if match else None


def extract_piccoma_wait_free_label(html_text: str) -> Optional[str]:
    text = _plain_text(html_text)
    match = re.search(r"(\d+\s*話分)\s*(?:待てば)?¥0", text)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    match = re.search(r"待てば¥0.*?(\d+\s*話分)", text)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def extract_piccoma_latest_episode_identifier(html_text: str, total_label: Optional[str]) -> Optional[str]:
    if total_label:
        match = re.search(r"(\d+)", total_label)
        if match:
            return match.group(1)
    text = _plain_text(html_text)
    numbers = [int(value) for value in re.findall(r"第\s*(\d+)\s*(?:話|審)", text)]
    return str(max(numbers)) if numbers else None


def piccoma_episode_title(identifier: str) -> str:
    return f"第{identifier}話"
```

Minimum behavior:

```python
def extract_piccoma_total_episode_label(html_text: str) -> Optional[str]:
    text = _plain_text(html_text)
    match = re.search(r"全\s*(\d+)\s*話", text)
    return f"全 {match.group(1)} 話" if match else None

def extract_piccoma_latest_episode_identifier(html_text: str, total_label: Optional[str]) -> Optional[str]:
    if total_label:
        match = re.search(r"(\d+)", total_label)
        if match:
            return match.group(1)
    text = _plain_text(html_text)
    numbers = [int(value) for value in re.findall(r"第\s*(\d+)\s*(?:話|審)", text)]
    return str(max(numbers)) if numbers else None
```

- [ ] **Step 3: Implement `PiccomaAdapter`**

```python
class PiccomaAdapter(SourceAdapter):
    source = "piccoma"

    def can_handle(self, seed_url: str) -> bool:
        return bool(parse_piccoma_product_url(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        product_id = extract_piccoma_product_id(seed_url)
        if not product_id:
            raise RuntimeError(f"{self.source}: could not parse product URL: {seed_url}")
        stable_work_id = f"{self.source}:{product_id}"
        return WorkDescriptor(
            source=self.source,
            work_id=stable_work_id,
            seed_url=canonical_piccoma_product_url(product_id),
            metadata={"series": stable_work_id, "productId": product_id},
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        product_id = work.metadata.get("productId") or extract_piccoma_product_id(work.seed_url)
        if not product_id:
            raise RuntimeError(f"{self.source}: productId is required")
        product_url = canonical_piccoma_product_url(product_id)
        html_text = http_client.get_text(product_url)
        page_title = html_title(html_text)
        series_title = extract_piccoma_series_title(html_text, page_title)
        if not series_title:
            raise SourceParseError(f"{self.source}: series title not found")
        total_label = extract_piccoma_total_episode_label(html_text)
        latest_identifier = extract_piccoma_latest_episode_identifier(html_text, total_label)
        if not latest_identifier:
            raise SourceParseError(f"{self.source}: latest episode identifier not found")
        extra = {}
        for key, value in {
            "freeEpisodeLabel": extract_piccoma_free_episode_label(html_text),
            "waitFreeLabel": extract_piccoma_wait_free_label(html_text),
            "totalEpisodeLabel": total_label,
        }.items():
            if value:
                extra[key] = value
        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=f"{self.source}:{product_id}:episode:{latest_identifier}",
            url=product_url,
            series=work.metadata.get("series"),
            series_title=series_title,
            episode_title=piccoma_episode_title(latest_identifier),
            page_title=page_title,
            extra=extra,
        )
```

- [ ] **Step 4: Register adapter**

Modify `manga_watch/sources/registry.py`:

```python
from .piccoma import PiccomaAdapter
```

Add `PiccomaAdapter()` to `REGISTERED_ADAPTERS` after `GaugauAdapter()` unless live design chooses another registry position.

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_sources
```

Expected: PASS for Piccoma source tests. If existing unrelated tests fail, capture exact failure before changing unrelated files.

- [ ] **Step 6: Commit**

```bash
git add manga_watch/sources/piccoma.py manga_watch/sources/registry.py tests/test_sources.py tests/fixtures/piccoma
git commit -m "feat: add piccoma source adapter"
```

### Task 4: Add Watchlist Support

**Files:**
- Modify: `manga_watch/watchlist.py`
- Modify: `tests/test_watchlist.py`

- [ ] **Step 1: Write failing watchlist tests**

Add tests near existing source-specific watchlist tests:

```python
def test_add_watchlist_url_accepts_piccoma_product_url(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        watchlist_path = Path(tmpdir) / "watchlist.json"
        write_watchlist(watchlist_path, [])

        payload = add_watchlist_url(
            "https://piccoma.com/web/product/58170?etype=episode",
            watchlist_path=str(watchlist_path),
        )
        saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

    self.assertEqual("added", payload["action"])
    self.assertEqual("piccoma:58170", payload["entry"]["id"])
    self.assertEqual("https://piccoma.com/web/product/58170?etype=episode", payload["entry"]["seed_url"])
    self.assertEqual(1, len(saved["works"]))
```

Add duplicate and unsupported URL type tests:

```python
def test_add_watchlist_url_reports_duplicate_for_piccoma_query_variant(self):
    existing_entry = {
        "id": "piccoma:58170",
        "source": "piccoma",
        "seed_url": "https://piccoma.com/web/product/58170?etype=episode",
        "enabled": True,
        "hidden": False,
        "notification_policy": {"mode": "all", "allowed_update_types": None},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        watchlist_path = Path(tmpdir) / "watchlist.json"
        write_watchlist(watchlist_path, [existing_entry])

        payload = add_watchlist_url(
            "https://piccoma.com/web/product/58170?from=search",
            watchlist_path=str(watchlist_path),
        )
        saved = json.loads(watchlist_path.read_text(encoding="utf-8"))

    self.assertEqual("duplicate", payload["action"])
    self.assertEqual(existing_entry, payload["existing"])
    self.assertEqual([existing_entry], saved["works"])


def test_add_watchlist_url_reports_unsupported_url_type_for_piccoma(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        watchlist_path = Path(tmpdir) / "watchlist.json"
        write_watchlist(watchlist_path, [])

        with self.assertRaises(WatchlistAddError) as ctx:
            add_watchlist_url(
                "https://piccoma.com/web/event/58170",
                watchlist_path=str(watchlist_path),
            )

    self.assertEqual("unsupported_url_type", ctx.exception.kind)
```

Use unsupported URL: `https://piccoma.com/web/event/58170`.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_watchlist
```

Expected: FAIL because Piccoma is not in `SOURCE_CAPABILITIES`.

- [ ] **Step 3: Add capability**

Add to `SOURCE_CAPABILITIES`:

```python
SourceCapability(
    source="piccoma",
    domains=("piccoma.com", "www.piccoma.com"),
    input_labels=("product URL",),
    examples=("https://piccoma.com/web/product/58170?etype=episode",),
),
```

- [ ] **Step 4: Run tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_watchlist
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add manga_watch/watchlist.py tests/test_watchlist.py
git commit -m "feat: support piccoma watchlist add"
```

### Task 5: Add Piccoma Search

**Files:**
- Modify: `manga_watch/source_search.py`
- Modify: `tests/test_source_search.py`
- Create: `tests/fixtures/source-search/piccoma/01-search.html`

- [ ] **Step 1: Add failing supported-source expectation**

In `tests/test_source_search.py`, add `"piccoma"` after `"gaugau"` in `test_supported_search_sources_match_registered_sources`.

- [ ] **Step 2: Add search fixture and parser test**

Create `tests/fixtures/source-search/piccoma/01-search.html` from sanitized live search HTML.

Test:

```python
def test_search_source_parses_piccoma_results(self):
    html = (FIXTURES_ROOT / "piccoma" / "01-search.html").read_text(encoding="utf-8")
    request_url = "https://piccoma.com/web/search?word=" + quote_plus("九条の大罪")

    results = search_source(
        "piccoma",
        "九条の大罪",
        http_client=StaticHttpClient({request_url: html}),
    )

    self.assertEqual(
        [
            SearchResult(
                source="piccoma",
                title="九条の大罪",
                seed_url="https://piccoma.com/web/product/58170?etype=episode",
                subtitle="piccoma",
            )
        ],
        results,
    )
```

Adjust `request_url` to the live-probe search URL template.

- [ ] **Step 3: Add noise-link test**

Add a test proving external links and non-product Piccoma links are ignored.

```python
def test_search_source_piccoma_ignores_non_product_links(self):
    html = """
    <html><body>
      <a href="https://piccoma.com/web/event/1">event</a>
      <a href="https://example.com/web/product/58170">external</a>
    </body></html>
    """
    request_url = "https://piccoma.com/web/search?word=" + quote_plus("九条の大罪")

    self.assertEqual(
        [],
        search_source("piccoma", "九条の大罪", http_client=StaticHttpClient({request_url: html})),
    )
```

- [ ] **Step 4: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_source_search
```

Expected: FAIL because search config does not contain `piccoma`.

- [ ] **Step 5: Implement source search config**

Add to `_SOURCE_SEARCH_CONFIG` with the live-probe URL:

```python
"piccoma": {
    "search_url": "https://piccoma.com/web/search?word={query}",
    "allowed_domains": ("piccoma.com", "www.piccoma.com"),
},
```

- [ ] **Step 6: Implement `_search_piccoma` if generic extractor is insufficient**

Use existing helper functions:

```python
def _search_piccoma(query: str, http_client: HttpClient, *, limit: int) -> List[SearchResult]:
    search_url = str(_SOURCE_SEARCH_CONFIG["piccoma"]["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()
    for match in re.finditer(r'<a\b[^>]*href="([^"]*/web/product/\d+[^"]*)"[^>]*>(.*?)</a>', html_text, re.I | re.S):
        resolved_url = _resolve_result_url(match.group(1), search_url=search_url)
        if not resolved_url or not _is_allowed_domain(resolved_url, ("piccoma.com", "www.piccoma.com")):
            continue
        canonical_seed_url = _canonical_seed_url_for_source("piccoma", resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue
        title = _extract_anchor_title(match.group(0), match.group(2))
        if not title:
            continue
        seen_seed_urls.add(canonical_seed_url)
        results.append(SearchResult("piccoma", title, canonical_seed_url, "piccoma"))
        if len(results) >= limit:
            break
    return results
```

Register it:

```python
_SEARCHERS["piccoma"] = _search_piccoma
```

- [ ] **Step 7: Run tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_source_search
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add manga_watch/source_search.py tests/test_source_search.py tests/fixtures/source-search/piccoma
git commit -m "feat: add piccoma source search"
```

### Task 6: Add Piccoma Source Drift Canary

**Files:**
- Modify: `manga_watch/source_drift.py`
- Modify: `tests/test_source_drift.py` only if targeted assertions are needed

- [ ] **Step 1: Write failing canary coverage**

Run existing canary tests first:

```bash
.venv/bin/python -m unittest tests.test_source_drift
```

Expected: FAIL after Piccoma registry addition because `DEFAULT_SOURCE_CANARY_CONTRACTS` has no `piccoma`.

- [ ] **Step 2: Add imports**

In `manga_watch/source_drift.py`:

```python
from .sources.piccoma import (
    PiccomaAdapter,
    extract_piccoma_free_episode_label,
    extract_piccoma_latest_episode_identifier,
    extract_piccoma_series_title,
    extract_piccoma_total_episode_label,
    extract_piccoma_wait_free_label,
)
```

- [ ] **Step 3: Add canary contract**

Add to `DEFAULT_SOURCE_CANARY_CONTRACTS`:

```python
"piccoma": SourceCanaryContract(
    source="piccoma",
    seed_url="https://piccoma.com/web/product/58170?etype=episode",
    fixture_bundle="tests/fixtures/piccoma/normal",
    monitored_signals=(
        "product page is publicly fetchable",
        "product page exposes the series title",
        "episode-reading latest identifier is discoverable",
        "public availability labels remain readable when present",
    ),
),
```

Use the final canary URL from Task 1 if different.

- [ ] **Step 4: Add canary runner**

```python
def _piccoma_canary(contract: SourceCanaryContract, http_client: HttpClient) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = PiccomaAdapter()
    work = adapter.normalize(contract.seed_url)
    html_text = http_client.get_text(work.seed_url)
    page_title = html_title(html_text)
    series_title = extract_piccoma_series_title(html_text, page_title)
    if not series_title:
        raise SourceParseError("piccoma: series title not found")
    total_label = extract_piccoma_total_episode_label(html_text)
    latest_identifier = extract_piccoma_latest_episode_identifier(html_text, total_label)
    if not latest_identifier:
        raise SourceParseError("piccoma: latest episode identifier not found")
    observations = [
        CanaryObservation("series_title", series_title),
        CanaryObservation("latest_episode_identifier", latest_identifier),
    ]
    for name, value in (
        ("free_episode_label", extract_piccoma_free_episode_label(html_text)),
        ("wait_free_label", extract_piccoma_wait_free_label(html_text)),
        ("total_episode_label", total_label),
    ):
        if value:
            observations.append(CanaryObservation(name, value))
    return ((work.seed_url,), tuple(observations))
```

Add to `CANARY_RUNNERS`:

```python
"piccoma": _piccoma_canary,
```

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_source_drift
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add manga_watch/source_drift.py tests/test_source_drift.py
git commit -m "feat: add piccoma source drift canary"
```

### Task 7: Document Piccoma Scope

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update supported sources table / text**

Add Piccoma to the supported sources section with accepted input and latest key shape:

```markdown
| Piccoma | product URL | `https://piccoma.com/web/product/<product_id>?etype=episode` | `piccoma:<product_id>` | `piccoma:<product_id>:episode:<episode>` |
```

- [ ] **Step 2: Document public-only exclusion**

Add a concise note near the supported source or source drift section:

```markdown
Piccoma support uses only unauthenticated public web product pages. It does not use login cookies, purchase state, viewing rights, app-only APIs, or inferred episode URLs. The crawler tracks episode-reading latest only; volume-reading latest is out of scope.
```

- [ ] **Step 3: Run docs-related tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_watchlist tests.test_source_search tests.test_sources
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document piccoma source scope"
```

### Task 8: Optional Real Search E2E Matrix

**Files:**
- Modify: `tests/test_source_search_e2e.py`

- [ ] **Step 1: Inspect current opt-in matrix**

Run:

```bash
sed -n '80,160p' tests/test_source_search_e2e.py
```

Expected: find representative title cases guarded by `RUN_REAL_SEARCH_E2E`.

- [ ] **Step 2: Add Piccoma representative case**

Add Piccoma only after Task 1 chooses a stable query and canary work.

Example:

```python
{"source": "piccoma", "query": "九条の大罪"},
```

- [ ] **Step 3: Run non-network unit tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_source_search
```

Expected: PASS. Do not require real E2E unless explicitly requested.

- [ ] **Step 4: Commit if changed**

```bash
git add tests/test_source_search_e2e.py
git commit -m "test: include piccoma in real search e2e matrix"
```

If no stable representative is chosen, skip this task and mention it in final handoff.

### Task 9: Final Verification

**Files:**
- No new edits expected

- [ ] **Step 1: Run required suite**

Run:

```bash
.venv/bin/python -m unittest tests.test_sources tests.test_watchlist tests.test_source_drift tests.test_source_search
```

Expected: PASS.

- [ ] **Step 2: Run Discord search impact suite**

Run:

```bash
.venv/bin/python -m unittest tests.test_discord_search tests.test_discord_supertwins tests.test_discord_interactions_search
```

Expected: PASS.

- [ ] **Step 3: Run live canary for Piccoma if network is allowed**

Run:

```bash
.venv/bin/python -m manga_watch.source_drift --source piccoma
```

Expected: `piccoma: OK`. If network is unavailable, record that live canary was not run.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git status --short
git log --oneline --max-count=8
```

Expected: clean worktree, commits separated by task.
