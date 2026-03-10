import json
import re
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


class KakuyomuAdapter(SourceAdapter):
    source = "kakuyomu"
    _SUPPORTED_URL = re.compile(
        r"^https?://(?:www\.)?kakuyomu\.jp/works/(\d+)(?:/episodes/(\d+))?/?(?:\?.*)?$"
    )

    def can_handle(self, seed_url: str) -> bool:
        return bool(self._SUPPORTED_URL.match(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        match = self._SUPPORTED_URL.match(seed_url)
        if not match:
            raise RuntimeError("kakuyomu: could not parse work/episode id")

        numeric_work_id = match.group(1)
        seed_episode_id = match.group(2)
        work_id = f"kakuyomu:{numeric_work_id}"
        metadata = {
            "series": work_id,
            "numericWorkId": numeric_work_id,
        }
        if seed_episode_id:
            metadata["seedEpisodeId"] = seed_episode_id
        return WorkDescriptor(
            source=self.source,
            work_id=work_id,
            seed_url=seed_url,
            metadata=metadata,
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        numeric_work_id = work.metadata.get("numericWorkId")
        if not numeric_work_id:
            raise RuntimeError("kakuyomu: work descriptor missing numericWorkId")

        work_url = f"https://kakuyomu.jp/works/{numeric_work_id}"
        html = self._fetch_work_page(work_url, http_client)
        next_data_raw = self._extract_next_data_raw(html)
        latest_id, latest_title = self._parse_latest_episode_from_next_data(next_data_raw)
        next_update_label = self._parse_next_update_label(next_data_raw, numeric_work_id)
        latest_url = f"{work_url}/episodes/{latest_id}"

        episode_html = self._fetch_episode_page(latest_url, http_client)
        page_title = html_title(episode_html)

        series_title = None
        episode_title = latest_title
        if page_title and " - " in page_title:
            parts = [part.strip() for part in page_title.split(" - ")]
            if len(parts) >= 2:
                episode_title = parts[0] or episode_title
                series_title = parts[1] or None

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=str(latest_id),
            url=latest_url,
            series=work.metadata.get("series") or work.work_id,
            series_title=series_title,
            episode_code=str(latest_id),
            episode_title=episode_title,
            page_title=page_title,
            extra={"nextUpdateLabel": next_update_label} if next_update_label else {},
        )

    def _fetch_work_page(self, work_url: str, http_client: HttpClient) -> str:
        return http_client.get_text(work_url)

    def _fetch_episode_page(self, episode_url: str, http_client: HttpClient) -> str:
        return http_client.get_text(episode_url)

    def _extract_next_data_raw(self, html: str) -> str:
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        if not match:
            raise SourceParseError("kakuyomu: __NEXT_DATA__ not found")
        return match.group(1)

    def _parse_latest_episode(self, html: str) -> Tuple[str, str]:
        return self._parse_latest_episode_from_next_data(self._extract_next_data_raw(html))

    def _parse_latest_episode_from_next_data(self, raw: str) -> Tuple[str, str]:
        episodes = []
        for episode_match in re.finditer(
            r'"Episode:(\d+)"\s*:\s*\{[^\}]*?"id"\s*:\s*"(\d+)"[^\}]*?"title"\s*:\s*"([^"]+)"[^\}]*?"publishedAt"\s*:\s*"([^"]+)"',
            raw,
        ):
            episode_id = episode_match.group(2)
            title = episode_match.group(3)
            published_at = episode_match.group(4)
            episodes.append((published_at, episode_id, title))

        if not episodes:
            raise SourceParseError("kakuyomu: no episodes found in __NEXT_DATA__")

        _, latest_id, latest_title = max(episodes, key=lambda episode: episode[0])
        return latest_id, latest_title

    def _parse_next_update_label(self, raw: str, numeric_work_id: str) -> Optional[str]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None

        apollo_state = payload.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__")
        if not isinstance(apollo_state, dict):
            return None

        schedule = apollo_state.get(f"WorkSchedule:{numeric_work_id}")
        if not isinstance(schedule, dict):
            work_data = apollo_state.get(f"Work:{numeric_work_id}")
            if not isinstance(work_data, dict):
                return None
            schedule_ref = work_data.get("schedule")
            if not isinstance(schedule_ref, dict):
                return None
            schedule = apollo_state.get(schedule_ref.get("__ref"))
            if not isinstance(schedule, dict):
                return None

        description = schedule.get("description")
        if not isinstance(description, str):
            return None

        label = re.sub(r"\s+", " ", description).strip()
        return label or None
