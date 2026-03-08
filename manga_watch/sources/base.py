from __future__ import annotations

import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, Mapping, Optional, Protocol
from urllib.parse import urlparse

import requests

UA = os.environ.get(
    "MANGA_WATCH_UA",
    "Mozilla/5.0 (X11; Linux) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
)


def _read_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _read_non_negative_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


TIMEOUT = _read_positive_int_env("MANGA_WATCH_HTTP_TIMEOUT", 25)
RETRY_COUNT = _read_positive_int_env("MANGA_WATCH_HTTP_RETRIES", 2)
RETRY_BACKOFF = _read_non_negative_float_env("MANGA_WATCH_HTTP_RETRY_BACKOFF", 0.5)
MAX_REQUESTS_PER_HOST = _read_positive_int_env("MANGA_WATCH_HTTP_WORKERS_PER_HOST", 2)


class HttpClient(Protocol):
    def get_text(self, url: str) -> str:
        ...


class RequestsHttpClient:
    def __init__(
        self,
        *,
        user_agent: str = UA,
        timeout: int = TIMEOUT,
        retry_count: int = RETRY_COUNT,
        retry_backoff: float = RETRY_BACKOFF,
        max_requests_per_host: int = MAX_REQUESTS_PER_HOST,
        session: Optional[requests.Session] = None,
        session_factory: Optional[Callable[[], requests.Session]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.retry_count = max(0, retry_count)
        self.retry_backoff = max(0.0, retry_backoff)
        self.max_requests_per_host = max(1, max_requests_per_host)
        self._shared_session = session
        self._session_factory = session_factory or requests.Session
        self._thread_local = threading.local()
        self._host_limiters: Dict[str, threading.BoundedSemaphore] = {}
        self._host_limiter_lock = threading.Lock()
        self.sleep = sleep

    def _session(self) -> requests.Session:
        if self._shared_session is not None:
            return self._shared_session

        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = self._session_factory()
            self._thread_local.session = session
        return session

    def _limiter_for(self, url: str) -> threading.BoundedSemaphore:
        host = urlparse(url).hostname or urlparse(url).netloc or "_default"
        with self._host_limiter_lock:
            limiter = self._host_limiters.get(host)
            if limiter is None:
                limiter = threading.BoundedSemaphore(self.max_requests_per_host)
                self._host_limiters[host] = limiter
            return limiter

    def get_text(self, url: str) -> str:
        for attempt in range(self.retry_count + 1):
            try:
                with self._limiter_for(url):
                    response = self._session().get(
                        url,
                        headers={"User-Agent": self.user_agent},
                        timeout=self.timeout,
                    )
                if self._is_retryable_status(response.status_code) and attempt < self.retry_count:
                    response.close()
                    self._sleep_before_retry(attempt)
                    continue
                response.raise_for_status()
                return response.text
            except requests.HTTPError as exc:
                if not self._is_retryable_http_error(exc) or attempt >= self.retry_count:
                    raise
                self._sleep_before_retry(attempt)
            except (requests.Timeout, requests.ConnectionError):
                if attempt >= self.retry_count:
                    raise
                self._sleep_before_retry(attempt)
        raise RuntimeError(f"request retries exhausted for {url}")

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code < 600

    def _is_retryable_http_error(self, exc: requests.HTTPError) -> bool:
        response = exc.response
        if response is None:
            return False
        return self._is_retryable_status(response.status_code)

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff <= 0:
            return
        self.sleep(self.retry_backoff * (2**attempt))


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
