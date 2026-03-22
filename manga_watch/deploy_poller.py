from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable, Mapping, Sequence

import requests

from manga_watch.ghcr_registry import resolve_public_tag_digest
from manga_watch.secret_redaction import redact_secret_text
from manga_watch.storage import advisory_file_lock, atomic_write_json

DEFAULT_POLLER_STATE = {
    "tracked_tag": "latest",
    "last_seen_digest": None,
    "last_attempted_digest": None,
    "last_deployed_digest": None,
    "previous_deployed_digest": None,
    "last_attempt_started_at": None,
    "last_success_at": None,
    "last_error": None,
}
DEFAULT_DISCORD_WEBHOOK_TIMEOUT = 10
COMPOSE_SERVICE_NAME = "comic-crawler"
DEFAULT_TRACKED_IMAGE = "ghcr.io/kentoku24/comic_crawler"
DEFAULT_TRACKED_TAG = "latest"
DEFAULT_COMPOSE_FILE = Path("docker-compose.deploy.yml")
DEFAULT_DEPLOY_ENV_PATH = Path(".env.deploy")
DEFAULT_POLLER_STATE_PATH = Path("/var/lib/comic-crawler/ghcr-poller-state.json")
SMOKE_CHECK_COMMAND = (
    "python",
    "-m",
    "manga_watch.check",
    "--status",
    "--format",
    "json",
    "--watchlist",
    "/app/manga_watch/watchlist.json",
    "--state",
    "/data/state.json",
)


@dataclass(frozen=True)
class PollPlan:
    action: str
    target_digest: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class DiscordWebhookNotifier:
    def __init__(
        self,
        webhook_url: str,
        *,
        timeout: int = DEFAULT_DISCORD_WEBHOOK_TIMEOUT,
        session: requests.Session | None = None,
    ):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.session = session or requests.Session()

    def send(self, payload: Mapping[str, object]) -> None:
        content = str(payload.get("content", "") or "")
        try:
            response = self.session.post(
                self.webhook_url,
                json={"content": content},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                "Discord webhook delivery failed: "
                f"{redact_secret_text(exc, secrets=(self.webhook_url,))}"
            ) from exc

        if 200 <= response.status_code < 300:
            return

        detail = redact_secret_text(
            response.text.strip().replace("\n", " "),
            secrets=(self.webhook_url,),
        )
        raise RuntimeError(f"Discord webhook returned HTTP {response.status_code}: {detail[:300]}")


def load_deploy_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()

    if not values.get("COMIC_CRAWLER_IMAGE_REF"):
        raise ValueError("deploy env must define COMIC_CRAWLER_IMAGE_REF")
    return values


def render_updated_deploy_env(existing_text: str, image_ref: str) -> str:
    rendered: list[str] = []
    replaced = False

    for line in existing_text.splitlines():
        key, separator, _ = line.partition("=")
        if separator and key.strip() == "COMIC_CRAWLER_IMAGE_REF":
            rendered.append(f"COMIC_CRAWLER_IMAGE_REF={image_ref}")
            replaced = True
            continue
        rendered.append(line)

    if not replaced:
        rendered.append(f"COMIC_CRAWLER_IMAGE_REF={image_ref}")

    return "\n".join(rendered) + "\n"


def validate_poller_state(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("poller state payload must be an object")

    state = dict(DEFAULT_POLLER_STATE)
    state.update(payload)

    tracked_tag = str(state.get("tracked_tag") or "").strip()
    state["tracked_tag"] = tracked_tag or DEFAULT_POLLER_STATE["tracked_tag"]

    for field_name in DEFAULT_POLLER_STATE:
        if field_name == "tracked_tag":
            continue
        value = state.get(field_name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"poller state {field_name} must be a string or null")

    return {field_name: state[field_name] for field_name in DEFAULT_POLLER_STATE}


def load_poller_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return dict(DEFAULT_POLLER_STATE)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_poller_state(payload)


def save_poller_state(path: Path, state: Mapping[str, object]) -> dict[str, object]:
    validated = validate_poller_state(state)
    atomic_write_json(str(path), validated)
    return validated


def plan_poll_result(*, tracked_tag: str, resolved_digest: str, state: Mapping[str, object]) -> PollPlan:
    if not tracked_tag.strip():
        raise ValueError("tracked_tag is required")
    if state.get("last_deployed_digest") == resolved_digest:
        return PollPlan(action="noop", target_digest=resolved_digest)
    return PollPlan(action="deploy", target_digest=resolved_digest)


def build_tracked_image_ref(tracked_image: str, tracked_tag: str) -> str:
    image = tracked_image.strip()
    tag = tracked_tag.strip()
    if not image:
        raise ValueError("tracked_image is required")
    if not tag:
        raise ValueError("tracked_tag is required")
    return f"{image}:{tag}"


def resolve_deploy_image_digest(
    image_ref: str,
    *,
    session: requests.Session | None = None,
) -> str:
    return resolve_public_tag_digest(image_ref, session=session)


def run_once(
    *,
    tracked_image: str,
    tracked_tag: str,
    compose_file: Path,
    deploy_env_path: Path,
    state_path: Path,
    lock_path: Path | None = None,
    dry_run: bool = False,
    resolve_digest: Callable[[str], str] = resolve_deploy_image_digest,
    command_runner: object | None = None,
    notifier: object | None = None,
) -> dict[str, object]:
    resolved_lock_path = lock_path or state_path.with_name(f"{state_path.name}.run")
    tracked_image_ref = build_tracked_image_ref(tracked_image, tracked_tag)

    with advisory_file_lock(str(resolved_lock_path)):
        resolved_digest = resolve_digest(tracked_image_ref)
        state = load_poller_state(state_path)
        state["tracked_tag"] = tracked_tag
        plan = plan_poll_result(
            tracked_tag=tracked_tag,
            resolved_digest=resolved_digest,
            state=state,
        )
        if dry_run:
            return {
                "result": "dry_run",
                "planned_action": plan.action,
                "tracked_image_ref": tracked_image_ref,
                "target_digest": resolved_digest,
            }

        state["last_seen_digest"] = resolved_digest

        if plan.action == "noop":
            saved_state = save_poller_state(state_path, state)
            return {
                "result": "noop",
                "state": saved_state,
                "target_digest": resolved_digest,
            }

        deploy_env = load_deploy_env(deploy_env_path)
        redaction_secrets = _redaction_secrets_from_env(deploy_env)
        resolved_notifier = notifier or _build_default_notifier(deploy_env)
        prior_deployed_digest = _coerce_optional_text(state.get("last_deployed_digest"))
        rollback_digest = prior_deployed_digest
        state["last_attempted_digest"] = resolved_digest
        state["last_attempt_started_at"] = _utcnow_isoformat()
        saved_state = save_poller_state(state_path, state)
        _emit_warning(
            _send_notification(
                resolved_notifier,
                event="detected",
                tracked_tag=tracked_tag,
                previous_digest=prior_deployed_digest,
                target_digest=resolved_digest,
                timestamp=state["last_attempt_started_at"],
                next_action="run deploy and smoke check",
                redaction_secrets=redaction_secrets,
            )
        )

        target_image_ref = build_digest_image_ref(tracked_image, resolved_digest)
        try:
            smoke_result = deploy_digest(
                compose_file=compose_file,
                deploy_env_path=deploy_env_path,
                target_image_ref=target_image_ref,
                command_runner=command_runner,
                redaction_secrets=redaction_secrets,
            )
        except Exception as exc:
            failure_timestamp = _utcnow_isoformat()
            failure_message = _redact_error(exc, redaction_secrets)
            state["last_error"] = failure_message
            saved_state = save_poller_state(state_path, state)
            _emit_warning(
                _send_notification(
                    resolved_notifier,
                    event="failed",
                    tracked_tag=tracked_tag,
                    previous_digest=rollback_digest,
                    target_digest=resolved_digest,
                    timestamp=failure_timestamp,
                    next_action=(
                        "attempt automatic rollback"
                        if rollback_digest
                        else "manual intervention required"
                    ),
                    error=failure_message,
                    redaction_secrets=redaction_secrets,
                )
            )
            if rollback_digest:
                rollback_image_ref = build_digest_image_ref(tracked_image, rollback_digest)
                try:
                    rollback_once(
                        compose_file=compose_file,
                        deploy_env_path=deploy_env_path,
                        previous_image_ref=rollback_image_ref,
                        command_runner=command_runner,
                        redaction_secrets=redaction_secrets,
                    )
                except Exception as rollback_exc:
                    rollback_message = _redact_error(rollback_exc, redaction_secrets)
                    state["last_error"] = (
                        f"{failure_message}; rollback_failed: {rollback_message}"
                    )
                    saved_state = save_poller_state(state_path, state)
                    _emit_warning(
                        _send_notification(
                            resolved_notifier,
                            event="rollback_failed",
                            tracked_tag=tracked_tag,
                            previous_digest=rollback_digest,
                            target_digest=resolved_digest,
                            timestamp=_utcnow_isoformat(),
                            next_action="manual rollback required",
                            error=state["last_error"],
                            redaction_secrets=redaction_secrets,
                        )
                    )
                    raise RuntimeError(state["last_error"]) from rollback_exc

                state["last_error"] = (
                    f"{failure_message}; rollback_succeeded: restored {rollback_digest}"
                )
                saved_state = save_poller_state(state_path, state)
                _emit_warning(
                    _send_notification(
                        resolved_notifier,
                        event="rollback_succeeded",
                        tracked_tag=tracked_tag,
                        previous_digest=rollback_digest,
                        target_digest=resolved_digest,
                        timestamp=_utcnow_isoformat(),
                        next_action="investigate failed digest before retrying deploy",
                        error=state["last_error"],
                        redaction_secrets=redaction_secrets,
                    )
                )
                raise RuntimeError(state["last_error"]) from exc

            raise RuntimeError(failure_message) from exc

        state["previous_deployed_digest"] = prior_deployed_digest
        state["last_deployed_digest"] = resolved_digest
        state["last_success_at"] = _utcnow_isoformat()
        state["last_error"] = None
        saved_state = save_poller_state(state_path, state)
        _emit_warning(
            _send_notification(
                resolved_notifier,
                event="deployed",
                tracked_tag=tracked_tag,
                previous_digest=prior_deployed_digest,
                target_digest=resolved_digest,
                timestamp=state["last_success_at"],
                next_action="wait for the next digest poll",
                redaction_secrets=redaction_secrets,
            )
        )
        return {
            "result": "deployed",
            "state": saved_state,
            "target_digest": resolved_digest,
            "smoke_check": smoke_result,
        }


def _utcnow_isoformat() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def deploy_digest(
    *,
    compose_file: Path,
    deploy_env_path: Path,
    target_image_ref: str,
    command_runner: object | None,
    redaction_secrets: Sequence[object],
) -> dict[str, object]:
    write_deploy_env_image_ref(deploy_env_path, target_image_ref)
    run_compose_command(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
        args=("pull", COMPOSE_SERVICE_NAME),
    )
    run_compose_command(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
        args=("up", "-d", COMPOSE_SERVICE_NAME),
    )
    assert_service_running(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
    )
    return run_smoke_check(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
    )


def rollback_once(
    *,
    compose_file: Path,
    deploy_env_path: Path,
    previous_image_ref: str,
    command_runner: object | None,
    redaction_secrets: Sequence[object],
) -> dict[str, object]:
    write_deploy_env_image_ref(deploy_env_path, previous_image_ref)
    run_compose_command(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
        args=("up", "-d", COMPOSE_SERVICE_NAME),
    )
    assert_service_running(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
    )
    return run_smoke_check(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
    )


def assert_service_running(
    *,
    compose_file: Path,
    deploy_env_path: Path,
    command_runner: object | None,
    redaction_secrets: Sequence[object],
) -> None:
    result = run_compose_command(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
        args=("ps", "--format", "json", COMPOSE_SERVICE_NAME),
    )
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"docker compose ps returned invalid JSON: {exc}") from exc

    services = payload if isinstance(payload, list) else [payload]
    for service in services:
        if not isinstance(service, Mapping):
            continue
        name = str(service.get("Service", service.get("Name", ""))).strip()
        state = str(service.get("State", service.get("Status", ""))).strip().lower()
        if name == COMPOSE_SERVICE_NAME and state == "running":
            return
    raise RuntimeError("docker compose ps did not report comic-crawler as running")


def run_smoke_check(
    *,
    compose_file: Path,
    deploy_env_path: Path,
    command_runner: object | None,
    redaction_secrets: Sequence[object],
) -> dict[str, object]:
    result = run_compose_command(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        command_runner=command_runner,
        redaction_secrets=redaction_secrets,
        args=("exec", "-T", COMPOSE_SERVICE_NAME, *SMOKE_CHECK_COMMAND),
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"smoke check returned invalid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("smoke check returned unexpected JSON payload")
    return dict(payload)


def run_compose_command(
    *,
    compose_file: Path,
    deploy_env_path: Path,
    command_runner: object | None,
    redaction_secrets: Sequence[object],
    args: Sequence[str],
) -> CommandResult:
    command = build_compose_command(
        compose_file=compose_file,
        deploy_env_path=deploy_env_path,
        args=args,
    )
    result = run_command(command, command_runner=command_runner)
    if result.returncode == 0:
        return result

    detail = _command_failure_detail(result)
    detail = redact_secret_text(detail, secrets=redaction_secrets)
    raise RuntimeError(f"command failed: {' '.join(command)}: {detail}")


def build_compose_command(
    *,
    compose_file: Path,
    deploy_env_path: Path,
    args: Sequence[str],
) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "--env-file",
        str(deploy_env_path),
        *args,
    ]


def run_command(command: Sequence[str], *, command_runner: object | None) -> CommandResult:
    runner = command_runner or _default_command_runner
    raw_result = runner(command)
    if isinstance(raw_result, CommandResult):
        return raw_result

    return CommandResult(
        returncode=int(getattr(raw_result, "returncode")),
        stdout=str(getattr(raw_result, "stdout", "") or ""),
        stderr=str(getattr(raw_result, "stderr", "") or ""),
    )


def _default_command_runner(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def build_digest_image_ref(tracked_image: str, digest: str) -> str:
    image = tracked_image.strip()
    normalized_digest = digest.strip()
    if not image:
        raise ValueError("tracked_image is required")
    if not normalized_digest:
        raise ValueError("digest is required")
    return f"{image}@{normalized_digest}"


def write_deploy_env_image_ref(path: Path, image_ref: str) -> None:
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated_text = render_updated_deploy_env(existing_text, image_ref)
    atomic_write_text(path, updated_text)


def atomic_write_text(path: Path, text: str) -> None:
    directory = str(path.parent)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _command_failure_detail(result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
    return detail[:500]


def _redaction_secrets_from_env(config: Mapping[str, str]) -> tuple[str, ...]:
    secrets: list[str] = []
    for key, value in config.items():
        normalized_key = key.strip().upper()
        if any(token in normalized_key for token in ("WEBHOOK", "TOKEN", "SECRET")):
            if value.strip():
                secrets.append(value.strip())
    return tuple(secrets)


def _build_default_notifier(config: Mapping[str, str]) -> DiscordWebhookNotifier | None:
    webhook_url = _coerce_optional_text(config.get("MANGA_WATCH_WEBHOOK_URL"))
    if not webhook_url:
        return None

    timeout_text = _coerce_optional_text(config.get("MANGA_WATCH_WEBHOOK_TIMEOUT"))
    timeout = DEFAULT_DISCORD_WEBHOOK_TIMEOUT
    if timeout_text is not None:
        try:
            timeout = int(timeout_text)
            if timeout <= 0:
                raise ValueError("timeout must be > 0")
        except ValueError:
            _emit_warning(
                "invalid MANGA_WATCH_WEBHOOK_TIMEOUT; "
                f"using default timeout {DEFAULT_DISCORD_WEBHOOK_TIMEOUT}s"
            )
            timeout = DEFAULT_DISCORD_WEBHOOK_TIMEOUT
    return DiscordWebhookNotifier(webhook_url, timeout=timeout)


def _send_notification(
    notifier: object | None,
    *,
    event: str,
    tracked_tag: str,
    previous_digest: str | None,
    target_digest: str,
    timestamp: str,
    next_action: str,
    redaction_secrets: Sequence[object],
    error: str | None = None,
) -> str | None:
    if notifier is None:
        return None

    payload = {
        "event": event,
        "content": redact_secret_text(
            "\n".join(
                [
                    f"tracked_tag: {tracked_tag}",
                    f"previous_digest: {previous_digest or 'none'}",
                    f"target_digest: {target_digest}",
                    f"result: {event}",
                    f"timestamp: {timestamp}",
                    f"next_action: {next_action}",
                    *([f"error: {error}"] if error else []),
                ]
            ),
            secrets=redaction_secrets,
        ),
    }
    try:
        notifier.send(payload)
    except Exception as exc:
        return _redact_error(exc, redaction_secrets)
    return None


def _emit_warning(message: str | None) -> None:
    if not message:
        return
    print(f"[deploy-poller] notification warning: {message}", file=sys.stderr)


def _coerce_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _redact_error(exc: Exception, secrets: Sequence[object]) -> str:
    return redact_secret_text(exc, secrets=secrets)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve the tracked GHCR image digest and run one deploy poll cycle."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run a single poll cycle and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve the current digest and print the planned result without editing files",
    )
    parser.add_argument(
        "--tracked-image",
        default=DEFAULT_TRACKED_IMAGE,
        help="tracked container image repository without tag or digest",
    )
    parser.add_argument(
        "--tracked-tag",
        default=DEFAULT_TRACKED_TAG,
        help="tracked image tag to resolve",
    )
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=DEFAULT_COMPOSE_FILE,
        help="deploy compose file used for pull/up/smoke-check commands",
    )
    parser.add_argument(
        "--deploy-env",
        type=Path,
        default=DEFAULT_DEPLOY_ENV_PATH,
        help="deploy env file containing COMIC_CRAWLER_IMAGE_REF and runtime config",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_POLLER_STATE_PATH,
        help="poller state file path",
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        help="advisory lock path prefix; storage helper appends .lock. Defaults to <state-path>.run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.once:
        parser.error("only --once is supported")

    try:
        outcome = run_once(
            tracked_image=args.tracked_image,
            tracked_tag=args.tracked_tag,
            compose_file=args.compose_file,
            deploy_env_path=args.deploy_env,
            state_path=args.state_path,
            lock_path=args.lock_path,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"[deploy-poller] error: {_redact_error(exc, ())}", file=sys.stderr)
        return 1

    print(json.dumps(outcome, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
