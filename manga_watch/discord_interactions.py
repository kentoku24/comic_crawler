from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional, Protocol

import google.auth
from google.auth.transport.requests import AuthorizedSession
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from manga_watch.discord_add import ADD_COMMAND, AddCommandHandler
from manga_watch.discord_fetch import FETCH_COMMAND, handle_fetch_trigger
from manga_watch.discord_latest import LATEST_COMMAND, handle_latest_query, validated_timezone_name
from manga_watch.discord_remove import REMOVE_COMMAND, RemoveCommandHandler
from manga_watch.discord_outbound import DiscordChannelClient
from manga_watch.notifier import build_named_notifiers
from manga_watch.runner import FETCH_ACCEPTED_MESSAGE, RunCoordinator, RunnerConfig, parse_bool
from manga_watch.secret_redaction import redact_secret_text
from manga_watch.secret_resolver import resolve_env_value
from manga_watch.storage import DEFAULT_WATCHLIST_PATH, get_state_path, storage_backend_from_env

INTERACTION_TYPE_PING = 1
INTERACTION_TYPE_APPLICATION_COMMAND = 2
INTERACTION_TYPE_MESSAGE_COMPONENT = 3
INTERACTION_RESPONSE_TYPE_PONG = 1
INTERACTION_RESPONSE_TYPE_CHANNEL_MESSAGE = 4
INTERACTION_RESPONSE_TYPE_UPDATE_MESSAGE = 7
EPHEMERAL_MESSAGE_FLAG = 64
DEFAULT_HTTP_TIMEOUT = 15
DEFAULT_INTERACTION_PATH = "/"
DEFAULT_FETCH_BACKEND = "coordinator"
FETCH_BACKEND_COORDINATOR = "coordinator"
FETCH_BACKEND_CLOUD_RUN_JOB = "cloud-run-job"
DEFAULT_CLOUD_RUN_JOB_NAME = "comic-crawler-job"
DEFAULT_CLOUD_RUN_REGION = "asia-northeast1"
DEFAULT_GOOGLE_AUTH_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
INVALID_SIGNATURE_MESSAGE = "invalid request signature"
FETCH_DISPATCH_FAILURE_MESSAGE = "fetch の起動に失敗しました。Cloud Run logs を確認してください。"


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _header_value(headers: Mapping[str, str], name: str) -> Optional[str]:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return _coerce_text(value)
    return None


def build_cloud_run_job_run_uri(*, project: str, region: str, job_name: str) -> str:
    return (
        f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job_name}:run"
    )


def build_manual_run_request_body(*, trigger_source: str = "manual") -> Dict[str, object]:
    return {
        "overrides": {
            "containerOverrides": [
                {
                    "env": [
                        {
                            "name": "MANGA_WATCH_TRIGGER_SOURCE",
                            "value": trigger_source,
                        }
                    ]
                }
            ]
        }
    }


def build_authorized_session() -> AuthorizedSession:
    credentials, _ = google.auth.default(scopes=[DEFAULT_GOOGLE_AUTH_SCOPE])
    return AuthorizedSession(credentials)


@dataclass(frozen=True)
class InteractionVerificationConfig:
    public_key: Optional[str]
    verification_disabled: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        secret_resolver: Callable[[str], Optional[str]] = resolve_env_value,
    ) -> "InteractionVerificationConfig":
        verification_disabled = parse_bool(
            os.environ.get("MANGA_WATCH_INSECURE_DISABLE_VERIFICATION"),
            default=False,
        )
        public_key = secret_resolver("DISCORD_APPLICATION_PUBLIC_KEY")
        if not verification_disabled and not public_key:
            raise ValueError(
                "DISCORD_APPLICATION_PUBLIC_KEY or "
                "DISCORD_APPLICATION_PUBLIC_KEY_SECRET_VERSION is required"
            )
        return cls(public_key=public_key, verification_disabled=verification_disabled)


class FetchDispatcher(Protocol):
    def dispatch(self) -> Mapping[str, object]:
        ...


class InProcessFetchDispatcher:
    def __init__(self, coordinator: RunCoordinator):
        self.coordinator = coordinator

    def dispatch(self) -> Mapping[str, object]:
        outcome = handle_fetch_trigger(FETCH_COMMAND, coordinator=self.coordinator)
        if outcome is None:
            return {"message": FETCH_ACCEPTED_MESSAGE}
        return outcome


class CloudRunJobFetchDispatcher:
    def __init__(
        self,
        *,
        project: str,
        region: str,
        job_name: str,
        session_factory: Callable[[], AuthorizedSession] = build_authorized_session,
        timeout: int = DEFAULT_HTTP_TIMEOUT,
        trigger_source: str = "manual",
    ):
        self.project = project
        self.region = region
        self.job_name = job_name
        self.session_factory = session_factory
        self.timeout = timeout
        self.trigger_source = trigger_source

    def dispatch(self) -> Mapping[str, object]:
        session = self.session_factory()
        response = session.post(
            build_cloud_run_job_run_uri(
                project=self.project,
                region=self.region,
                job_name=self.job_name,
            ),
            json=build_manual_run_request_body(trigger_source=self.trigger_source),
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
            allow_redirects=False,
        )
        if 200 <= response.status_code < 300:
            return {
                "ok": True,
                "accepted": True,
                "background": True,
                "message": FETCH_ACCEPTED_MESSAGE,
            }

        detail = redact_secret_text(response.text.strip().replace("\n", " "))
        raise RuntimeError(
            f"Cloud Run Job launch failed with HTTP {response.status_code}: {detail[:300]}"
        )


def build_fetch_dispatcher_from_env(
    *,
    coordinator: Optional[RunCoordinator],
    session_factory: Callable[[], AuthorizedSession] = build_authorized_session,
) -> FetchDispatcher:
    backend = _coerce_text(os.environ.get("MANGA_WATCH_FETCH_BACKEND")) or DEFAULT_FETCH_BACKEND
    if backend == FETCH_BACKEND_COORDINATOR:
        if coordinator is None:
            raise ValueError("RunCoordinator is required when MANGA_WATCH_FETCH_BACKEND=coordinator")
        return InProcessFetchDispatcher(coordinator)
    if backend != FETCH_BACKEND_CLOUD_RUN_JOB:
        raise ValueError(f"Unsupported MANGA_WATCH_FETCH_BACKEND: {backend}")

    project = (
        _coerce_text(os.environ.get("MANGA_WATCH_GCP_PROJECT"))
        or _coerce_text(os.environ.get("GOOGLE_CLOUD_PROJECT"))
        or _coerce_text(os.environ.get("GCLOUD_PROJECT"))
    )
    if not project:
        raise ValueError(
            "MANGA_WATCH_GCP_PROJECT or GOOGLE_CLOUD_PROJECT is required when "
            "MANGA_WATCH_FETCH_BACKEND=cloud-run-job"
        )

    region = (
        _coerce_text(os.environ.get("MANGA_WATCH_CLOUD_RUN_REGION"))
        or _coerce_text(os.environ.get("MANGA_WATCH_GCP_REGION"))
        or DEFAULT_CLOUD_RUN_REGION
    )
    job_name = (
        _coerce_text(os.environ.get("MANGA_WATCH_CLOUD_RUN_JOB_NAME"))
        or DEFAULT_CLOUD_RUN_JOB_NAME
    )
    return CloudRunJobFetchDispatcher(
        project=project,
        region=region,
        job_name=job_name,
        session_factory=session_factory,
    )


class DiscordRequestVerifier:
    def __init__(self, public_key: str):
        try:
            self._verify_key = VerifyKey(bytes.fromhex(public_key))
        except ValueError as exc:
            raise ValueError("DISCORD_APPLICATION_PUBLIC_KEY must be a hex-encoded Ed25519 key") from exc

    def verify(self, *, signature: str, timestamp: str, body: bytes) -> bool:
        try:
            self._verify_key.verify(timestamp.encode("utf-8") + body, bytes.fromhex(signature))
        except (BadSignatureError, ValueError):
            return False
        return True


@dataclass(frozen=True)
class InteractionHttpResponse:
    status_code: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"


def json_response(status_code: int, payload: Mapping[str, object]) -> InteractionHttpResponse:
    return InteractionHttpResponse(
        status_code=status_code,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def text_response(status_code: int, message: str) -> InteractionHttpResponse:
    return InteractionHttpResponse(
        status_code=status_code,
        body=message.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )


def interaction_message_response(content: str) -> InteractionHttpResponse:
    return interaction_payload_response(
        INTERACTION_RESPONSE_TYPE_CHANNEL_MESSAGE,
        {"content": content},
        ephemeral=False,
    )


def interaction_payload_response(
    response_type: int,
    data: Mapping[str, object],
    *,
    ephemeral: bool = False,
) -> InteractionHttpResponse:
    payload = {
        "type": response_type,
        "data": {
            "allowed_mentions": {"parse": []},
            **dict(data),
        },
    }
    if ephemeral:
        payload["data"]["flags"] = EPHEMERAL_MESSAGE_FLAG
    return json_response(200, payload)


def interaction_ephemeral_response(data: Mapping[str, object]) -> InteractionHttpResponse:
    return interaction_payload_response(
        INTERACTION_RESPONSE_TYPE_CHANNEL_MESSAGE,
        data,
        ephemeral=True,
    )


@dataclass
class DiscordInteractionService:
    timezone_name: str
    fetch_dispatcher: FetchDispatcher
    interaction_path: str = DEFAULT_INTERACTION_PATH
    watchlist_path: Optional[str] = None
    state_path: Optional[str] = None
    verifier: Optional[DiscordRequestVerifier] = None
    verification_disabled: bool = False
    latest_handler: Callable[..., Optional[str]] = handle_latest_query
    add_handler: Optional[AddCommandHandler] = None
    remove_handler: Optional[RemoveCommandHandler] = None

    def handle_request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> InteractionHttpResponse:
        if path != self.interaction_path:
            return text_response(404, "not found")
        if method != "POST":
            return text_response(405, "method not allowed")
        if not self.verification_disabled and not self._verify_request(headers=headers, body=body):
            return text_response(401, INVALID_SIGNATURE_MESSAGE)

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return text_response(400, "invalid json payload")

        if not isinstance(payload, Mapping):
            return text_response(400, "invalid interaction payload")

        interaction_type = int(payload.get("type") or 0)
        if interaction_type == INTERACTION_TYPE_PING:
            return json_response(200, {"type": INTERACTION_RESPONSE_TYPE_PONG})
        if interaction_type == INTERACTION_TYPE_APPLICATION_COMMAND:
            return self._handle_application_command(payload)
        if interaction_type == INTERACTION_TYPE_MESSAGE_COMPONENT:
            return self._handle_message_component(payload)
        return text_response(400, "unsupported interaction type")

    def _handle_application_command(self, payload: Mapping[str, object]) -> InteractionHttpResponse:
        command_name = self._command_name(payload)
        if command_name == LATEST_COMMAND:
            content = self.latest_handler(
                LATEST_COMMAND,
                watchlist_path=self.watchlist_path,
                state_path=self.state_path,
                timezone_name=self.timezone_name,
            )
            if not content:
                return text_response(500, "empty interaction response")
            return interaction_message_response(content)
        if command_name == FETCH_COMMAND:
            try:
                content = str(self.fetch_dispatcher.dispatch().get("message") or "").strip()
            except Exception:
                return interaction_message_response(FETCH_DISPATCH_FAILURE_MESSAGE)
            if not content:
                return text_response(500, "empty interaction response")
            return interaction_message_response(content)
        if command_name == ADD_COMMAND and self.add_handler is not None:
            response_payload = self.add_handler.start(
                url=self._command_option(payload, "url"),
                watchlist_path=self.watchlist_path,
            )
            return interaction_message_response(str(response_payload.get("content") or "").strip())
        if command_name == REMOVE_COMMAND and self.remove_handler is not None:
            payload = self.remove_handler.start(
                watchlist_path=self.watchlist_path,
                state_path=self.state_path,
            )
            return interaction_ephemeral_response(payload)
        return text_response(400, f"unsupported command: {command_name or '(missing)'}")

    def _handle_message_component(self, payload: Mapping[str, object]) -> InteractionHttpResponse:
        if self.remove_handler is None:
            return text_response(400, "unsupported interaction type")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return text_response(400, "invalid interaction payload")
        response_payload = self.remove_handler.handle_component(
            data,
            watchlist_path=self.watchlist_path,
            state_path=self.state_path,
        )
        return interaction_payload_response(
            INTERACTION_RESPONSE_TYPE_UPDATE_MESSAGE,
            response_payload,
        )

    def _verify_request(self, *, headers: Mapping[str, str], body: bytes) -> bool:
        if self.verifier is None:
            return False
        signature = _header_value(headers, "X-Signature-Ed25519")
        timestamp = _header_value(headers, "X-Signature-Timestamp")
        if not signature or not timestamp:
            return False
        return self.verifier.verify(signature=signature, timestamp=timestamp, body=body)

    @staticmethod
    def _command_name(payload: Mapping[str, object]) -> str:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return ""
        return str(data.get("name") or "").strip().lower()

    @staticmethod
    def _command_option(payload: Mapping[str, object], option_name: str) -> Optional[str]:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return None
        options = data.get("options")
        if not isinstance(options, list):
            return None
        normalized_name = option_name.strip().lower()
        for option in options:
            if not isinstance(option, Mapping):
                continue
            name = str(option.get("name") or "").strip().lower()
            if name != normalized_name:
                continue
            return _coerce_text(option.get("value"))
        return None


def interaction_timezone_name_from_env() -> str:
    return validated_timezone_name(os.environ.get("TZ", "Asia/Tokyo"))


def interaction_watchlist_path_from_env() -> str:
    return os.environ.get(
        "MANGA_WATCH_WATCHLIST",
        os.environ.get("MANGA_WATCH_URLS", DEFAULT_WATCHLIST_PATH),
    )


def build_interaction_service_from_env(
    *,
    runner_config: Optional[RunnerConfig] = None,
    interaction_path: Optional[str] = None,
    session_factory: Callable[[], AuthorizedSession] = build_authorized_session,
) -> DiscordInteractionService:
    backend = _coerce_text(os.environ.get("MANGA_WATCH_FETCH_BACKEND")) or DEFAULT_FETCH_BACKEND
    storage_backend = storage_backend_from_env()
    verification = InteractionVerificationConfig.from_env()

    coordinator = None
    state_path = get_state_path()
    if runner_config is not None:
        timezone_name = runner_config.timezone_name
        watchlist_path = runner_config.watchlist_path
        config = runner_config
    else:
        timezone_name = interaction_timezone_name_from_env()
        watchlist_path = interaction_watchlist_path_from_env()
        config = None

    if backend == FETCH_BACKEND_COORDINATOR:
        config = config or RunnerConfig.from_env(require_discord=False)
        timezone_name = config.timezone_name
        watchlist_path = config.watchlist_path
        named_notifiers = build_named_notifiers(config.notifier_config)
        discord_client = (
            DiscordChannelClient(config.discord_outbound_config)
            if config.discord_outbound_config is not None
            else None
        )
        coordinator = RunCoordinator(
            config,
            named_notifiers=named_notifiers,
            discord_client=discord_client,
        )

    fetch_dispatcher = build_fetch_dispatcher_from_env(
        coordinator=coordinator,
        session_factory=session_factory,
    )
    verifier = None
    if not verification.verification_disabled and verification.public_key is not None:
        verifier = DiscordRequestVerifier(verification.public_key)

    return DiscordInteractionService(
        timezone_name=timezone_name,
        fetch_dispatcher=fetch_dispatcher,
        interaction_path=interaction_path or os.environ.get("MANGA_WATCH_INTERACTION_PATH", DEFAULT_INTERACTION_PATH),
        watchlist_path=watchlist_path,
        state_path=state_path,
        verifier=verifier,
        verification_disabled=verification.verification_disabled,
        add_handler=AddCommandHandler(),
        remove_handler=RemoveCommandHandler(backend=storage_backend),
    )
