from __future__ import annotations

import html
from html.parser import HTMLParser
import json
import re
from typing import Iterable, Optional

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_PRODUCT_URL = re.compile(
    r"^https?://(?:www\.)?piccoma\.com/web/product/(\d+)(?:/)?(?:\?.*)?$"
)
_LD_JSON_SCRIPT = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)

def canonical_piccoma_product_url(product_id: str) -> str:
    return f"https://piccoma.com/web/product/{product_id}?etype=episode"


def canonical_piccoma_episodes_url(product_id: str) -> str:
    return f"https://piccoma.com/web/product/{product_id}/episodes?etype=E"


def extract_piccoma_product_id(seed_url: str) -> Optional[str]:
    match = _PRODUCT_URL.match(str(seed_url or "").strip())
    if not match:
        return None
    return match.group(1)


def parse_piccoma_product_url(seed_url: str) -> Optional[str]:
    product_id = extract_piccoma_product_id(seed_url)
    if not product_id:
        return None
    return canonical_piccoma_product_url(product_id)


def extract_piccoma_series_title(html_text: str, page_title: Optional[str] = None) -> Optional[str]:
    name = extract_piccoma_ld_json_product_name(html_text)
    if name:
        return name

    heading = re.search(r"<h1[^>]*>(.*?)</h1>", html_text or "", re.I | re.S)
    if heading:
        title = _plain_text(heading.group(1))
        if title:
            return title

    if page_title:
        title = re.split(r"[｜|]", page_title, maxsplit=1)[0].strip()
        if title:
            return title
    return None


def extract_piccoma_ld_json_product_name(html_text: str) -> Optional[str]:
    for match in _LD_JSON_SCRIPT.finditer(html_text or ""):
        name = _product_name_from_ld_json(match.group(1), product_only=True)
        if name:
            return name
    return None


def extract_piccoma_total_episode_label(html_text: str) -> Optional[str]:
    match = re.search(r"全\s*(\d+)\s*話", _plain_text(html_text))
    if not match:
        return None
    return f"全 {match.group(1)} 話"


def extract_piccoma_free_episode_label(html_text: str) -> Optional[str]:
    match = re.search(r"(\d+\s*話分無料|\d+\s*話無料)", _plain_text(html_text))
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1))


def extract_piccoma_wait_free_label(html_text: str) -> Optional[str]:
    text = _plain_text(html_text)
    match = re.search(r"(\d+\s*話分)\s*(?:待てば)?¥0", text)
    if not match:
        match = re.search(r"待てば¥0.*?(\d+\s*話分)", text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def extract_piccoma_latest_episode(episodes_html: str) -> tuple[Optional[str], Optional[str]]:
    parser = _PiccomaEpisodeListParser()
    parser.feed(episodes_html or "")
    return parser.latest_episode()


def extract_piccoma_episode_list_latest_episode(episodes_html: str) -> tuple[Optional[str], Optional[str]]:
    parser = _PiccomaEpisodeListParser()
    parser.feed(episodes_html or "")
    return parser.latest_episode_from_episode_list()


class _PiccomaEpisodeListParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._episode_list_depth: Optional[int] = None
        self._active_items = []
        self._episode_list_items: list[tuple[str, Optional[str]]] = []

    def handle_starttag(self, tag, attrs):
        attrs_by_name = {name: value for name, value in attrs}
        next_depth = self._depth + 1
        if attrs_by_name.get("id") == "js_episodeList":
            self._episode_list_depth = next_depth

        episode_id = (attrs_by_name.get("data-episode_id") or "").strip()
        if episode_id:
            self._active_items.append(
                {
                    "depth": next_depth,
                    "episode_id": episode_id,
                    "in_episode_list": self._episode_list_depth is not None,
                    "chunks": [],
                    "title_chunks": [],
                    "title_depth": None,
                }
            )

        if tag.lower() in {"h1", "h2", "h3"}:
            for item in self._active_items:
                if item["title_depth"] is None:
                    item["title_depth"] = next_depth

        self._depth = next_depth

    def handle_startendtag(self, tag, attrs):
        attrs_by_name = {name: value for name, value in attrs}
        episode_id = (attrs_by_name.get("data-episode_id") or "").strip()
        if episode_id:
            self._append_item(episode_id, None, self._episode_list_depth is not None)

    def handle_endtag(self, tag):
        for item in self._active_items:
            if item["title_depth"] == self._depth:
                item["title_depth"] = None

        while self._active_items and self._active_items[-1]["depth"] == self._depth:
            item = self._active_items.pop()
            title_chunks = item["title_chunks"] or item["chunks"]
            title = " ".join(title_chunks).strip() or None
            self._append_item(item["episode_id"], title, item["in_episode_list"])

        if self._episode_list_depth == self._depth:
            self._episode_list_depth = None
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        text = (data or "").strip()
        if not text:
            return
        for item in self._active_items:
            if item["title_depth"] is not None:
                item["title_chunks"].append(text)
            else:
                item["chunks"].append(text)

    def latest_episode(self) -> tuple[Optional[str], Optional[str]]:
        return self.latest_episode_from_episode_list()

    def latest_episode_from_episode_list(self) -> tuple[Optional[str], Optional[str]]:
        if not self._episode_list_items:
            return None, None
        return self._episode_list_items[-1]

    def _append_item(self, episode_id: str, title: Optional[str], in_episode_list: bool):
        item = (episode_id, title)
        if in_episode_list:
            self._episode_list_items.append(item)


def _plain_text(html_text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", html_text or "")
    return html.unescape(re.sub(r"\s+", " ", no_tags)).strip()


def _product_name_from_ld_json(raw_json: str, *, product_only: bool = False) -> Optional[str]:
    try:
        payload = json.loads(html.unescape(raw_json))
    except json.JSONDecodeError:
        return None

    product_candidates = []
    named_candidates = []
    for candidate in _walk_json_dicts(payload):
        raw_type = candidate.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if "Product" in types:
            product_candidates.append(candidate)
        elif candidate.get("name"):
            named_candidates.append(candidate)

    candidates = product_candidates if product_only else product_candidates + named_candidates
    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        if name:
            return name
    return None


def _walk_json_dicts(value) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_dicts(child)


def _piccoma_episode_title(identifier: str, title: Optional[str]) -> str:
    return title or f"episode:{identifier}"


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
            metadata={
                "series": stable_work_id,
                "productId": product_id,
            },
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        product_id = work.metadata.get("productId") or extract_piccoma_product_id(work.seed_url)
        if not product_id:
            raise RuntimeError(f"{self.source}: productId is required")

        product_url = canonical_piccoma_product_url(product_id)
        product_html = http_client.get_text(product_url)
        page_title = html_title(product_html)
        series_title = extract_piccoma_series_title(product_html, page_title)
        if not series_title:
            raise SourceParseError(f"{self.source}: series title not found")

        episodes_html = http_client.get_text(canonical_piccoma_episodes_url(product_id))
        latest_identifier, latest_title = extract_piccoma_episode_list_latest_episode(episodes_html)
        if not latest_identifier:
            raise SourceParseError(f"{self.source}: latest episode identifier not found")

        extra = {}
        for key, value in (
            ("freeEpisodeLabel", extract_piccoma_free_episode_label(product_html)),
            ("waitFreeLabel", extract_piccoma_wait_free_label(product_html)),
            ("totalEpisodeLabel", extract_piccoma_total_episode_label(product_html)),
        ):
            if value:
                extra[key] = value

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=f"{self.source}:{product_id}:episode:{latest_identifier}",
            url=product_url,
            series=work.metadata.get("series"),
            series_title=series_title,
            episode_title=_piccoma_episode_title(latest_identifier, latest_title),
            page_title=page_title,
            extra=extra,
        )
