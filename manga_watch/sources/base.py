from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Protocol

import requests

UA = os.environ.get(
    "MANGA_WATCH_UA",
    "Mozilla/5.0 (X11; Linux) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
)
TIMEOUT = 25


class HttpClient(Protocol):
    def get_text(self, url: str) -> str:
        ...


class RequestsHttpClient:
    def __init__(
        self,
        *,
        user_agent: str = UA,
        timeout: int = TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.session = session or requests.Session()

    def get_text(self, url: str) -> str:
        response = self.session.get(
            url,
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text


class SourceParseError(RuntimeError):
    """Raised when a source page can be fetched but not parsed."""


@dataclass(frozen=True)
class WorkDescriptor:
    source: str
    work_id: str
    seed_url: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, str]:
        data = {
            "source": self.source,
            "kind": self.source,
            "workId": self.work_id,
            "seedUrl": self.seed_url,
        }
        for key, value in self.metadata.items():
            if value is None:
                continue
            data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "WorkDescriptor":
        source = str(data.get("source") or data.get("kind") or "")
        if not source:
            raise RuntimeError("work descriptor missing source")

        work_id = str(data.get("workId") or data.get("series") or data.get("seedUrl") or "")
        if not work_id:
            raise RuntimeError("work descriptor missing workId")

        seed_url = str(data.get("seedUrl") or "")
        if not seed_url:
            raise RuntimeError("work descriptor missing seedUrl")

        metadata: Dict[str, str] = {}
        for key, value in data.items():
            if key in {"source", "kind", "workId", "seedUrl"} or value is None:
                continue
            metadata[key] = str(value)

        return cls(
            source=source,
            work_id=work_id,
            seed_url=seed_url,
            metadata=metadata,
        )


@dataclass(frozen=True)
class LatestEpisode:
    source: str
    work_id: str
    latest_key: str
    url: str
    series: Optional[str] = None
    series_title: Optional[str] = None
    episode_code: Optional[str] = None
    episode_title: Optional[str] = None
    page_title: Optional[str] = None
    extra: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, str]:
        data = {
            "source": self.source,
            "workId": self.work_id,
            "latestKey": self.latest_key,
            "url": self.url,
        }
        if self.series:
            data["series"] = self.series
        if self.series_title:
            data["seriesTitle"] = self.series_title
        if self.episode_code:
            data["episodeCode"] = self.episode_code
        if self.episode_title:
            data["episodeTitle"] = self.episode_title
        if self.page_title:
            data["pageTitle"] = self.page_title
        for key, value in self.extra.items():
            if value is None:
                continue
            data[key] = value
        return data


class SourceAdapter(ABC):
    source: str

    @abstractmethod
    def can_handle(self, seed_url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, seed_url: str) -> WorkDescriptor:
        raise NotImplementedError

    @abstractmethod
    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        raise NotImplementedError
