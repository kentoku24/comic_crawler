from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from manga_watch.sources.piccoma import canonical_piccoma_product_url, extract_piccoma_product_id


class _TrackingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.read_episode_number: Optional[int] = None
        self.read_episode_id: Optional[str] = None
        self.next_episode_number: Optional[int] = None
        self.next_episode_id: Optional[str] = None
        self.charge_time: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        attrs_by_name = {name: value for name, value in attrs}
        class_names = set(str(attrs_by_name.get("class") or "").split())
        if "js_readContinue" in class_names:
            current_order = _optional_int(attrs_by_name.get("data-current_order_value"))
            if current_order is not None and (
                self.read_episode_number is None or current_order > self.read_episode_number
            ):
                self.read_episode_number = current_order
                self.read_episode_id = _coerce_text(attrs_by_name.get("data-current_episode_id"))
                self.next_episode_number = _optional_int(attrs_by_name.get("data-next_order_value"))
                self.next_episode_id = _coerce_text(attrs_by_name.get("data-next_episode_id"))

        if attrs_by_name.get("id") == "js_freeChargeBar":
            self.charge_time = _coerce_text(attrs_by_name.get("data-charge_time"))


def extract_piccoma_authenticated_tracking(
    html_text: str,
    *,
    timezone_name: str = "Asia/Tokyo",
) -> dict[str, object]:
    parser = _TrackingParser()
    parser.feed(html_text or "")

    tracking: dict[str, object] = {}
    if parser.read_episode_number is not None:
        tracking["piccomaReadEpisodeNumber"] = parser.read_episode_number
    if parser.read_episode_id:
        tracking["piccomaReadEpisodeId"] = parser.read_episode_id
    if parser.next_episode_number is not None:
        tracking["piccomaNextEpisodeNumber"] = parser.next_episode_number
    if parser.next_episode_id:
        tracking["piccomaNextEpisodeId"] = parser.next_episode_id
    if parser.read_episode_number is not None and parser.charge_time:
        recovery_at = _parse_piccoma_datetime(parser.charge_time, timezone_name=timezone_name)
        if recovery_at is not None:
            tracking["piccomaWaitFreeNextRecoveryAt"] = recovery_at
    return tracking


def merge_piccoma_authenticated_tracking(
    latest: Mapping[str, object],
    tracking: Mapping[str, object],
) -> dict[str, object]:
    if not tracking:
        return dict(latest)
    merged = dict(latest)
    merged.update(tracking)
    return merged


def sync_piccoma_authenticated_tracking(
    item: Mapping[str, object],
    latest: Mapping[str, object],
    http_client,
    *,
    timezone_name: str = "Asia/Tokyo",
) -> dict[str, object]:
    if str(latest.get("source") or "") != "piccoma":
        return dict(latest)
    product_id = extract_piccoma_product_id(str(item.get("seedUrl") or item.get("seed_url") or ""))
    if not product_id:
        return dict(latest)

    html_text = http_client.get_text(canonical_piccoma_product_url(product_id))
    tracking = extract_piccoma_authenticated_tracking(html_text, timezone_name=timezone_name)
    return merge_piccoma_authenticated_tracking(latest, tracking)


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_piccoma_datetime(value: str, *, timezone_name: str) -> Optional[int]:
    try:
        dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return int(dt.replace(tzinfo=ZoneInfo(timezone_name)).timestamp())
