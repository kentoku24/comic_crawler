from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable, Mapping, Sequence

import requests

from manga_watch.ghcr_registry import resolve_public_tag_digest
from manga_watch.secret_redaction import redact_secret_text
from manga_watch.storage import advisory_file_lock

DEFAULT_DISCORD_WEBHOOK_TIMEOUT = 10
COMPOSE_SERVICE_NAME = "comic-crawler"
DEFAULT_TRACKED_IMAGE = "ghcr.io/kentoku24/comic_crawler"
DEFAULT_TRACKED_TAG = "latest"
DEFAULT_COMPOSE_FILE = Path("docker-compose.deploy.yml")
DEFAULT_DEPLOY_ENV_PATH = Path(".env.deploy")
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
        try:
            response = self.session.post(
                self.webhook_url,
                json={"content": str(payload.get("content", "") or "")},
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

    image_ref = str(values.get("COMIC_CRAWLER_IMAGE_REF") or "").strip()
    if not image_ref:
        raise ValueError("deploy env must define COMIC_CRAWLER_IMAGE_REF")
    if "@" not in image_ref:
        raise ValueError("COMIC_CRAWLER_IMAGE_REF must use an immutable digest reference")
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


def build_tracked_image_ref(tracked_image: str, tracked_tag: str) -> str:
    image = tracked_image.strip()
    tag = tracked_tag.strip()
    if not image:
        raise ValueError("tracked_image is required")
    if not tag:
        raise ValueError("tracked_tag is required")
    return f"{image}:{tag}"


def build_digest_image_ref(tracked_image: str, digest: str) -> str:
    image = tracked_image.strip()
    normalized_digest = digest.strip()
    if not image:
        raise ValueError("tracked_image is required")
    if not normalized_digest:
        raise ValueError("digest is required")
    return f"{image}@{normalized_digest}"


def parse_digest_image_ref(image_ref: str) -> tuple[str, str]:
    image, separator, digest = image_ref.strip().partition("@")
    if not separator or not image or not digest:
        raise ValueError(f"expected digest image reference, got: {image_ref}")
    return image, digest


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
    lock_path: Path | None = None,
    resolve_digest: Callable[[str], str] = resolve_deploy_image_digest,
    command_runner: object | None = None,
    notifier: object | None = None,
) -> dict[str, object]:
    tracked_image_ref = build_tracked_image_ref(tracked_image, tracked_tag)
    resolved_lock_path = lock_path or deploy_env_path

    with advisory_file_lock(str(resolved_lock_path)):
        deploy_env = load_deploy_env(deploy_env_path)
        current_image_ref = deploy_env["COMIC_CRAWLER_IMAGE_REF"]
        _, current_digest = parse_digest_image_ref(current_image_ref)
        resolved_digest = resolve_digest(tracked_image_ref)
        if current_digest == resolved_digest:
            return {"result": "noop", "target_digest": resolved_digest}

        redaction_secrets = _redaction_secrets_from_env(deploy_env)
        resolved_notifier = notifier or _build_default_notifier(deploy_env)
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
            failure_message = _redact_error(exc, redaction_secrets)
            _emit_warning(
                _send_notification(
                    resolved_notifier,
                    event="failed",
                    tracked_tag=tracked_tag,
                    previous_digest=current_digest,
                    target_digest=resolved_digest,
                    next_action="attempt automatic rollback",
                    error=failure_message,
                    redaction_secrets=redaction_secrets,
                )
            )
            rollback_once(
                compose_file=compose_file,
                deploy_env_path=deploy_env_path,
                previous_image_ref=current_image_ref,
                command_runner=command_runner,
                redaction_secrets=redaction_secrets,
            )
            _emit_warning(
                _send_notification(
                    resolved_notifier,
                    event="rollback_succeeded",
                    tracked_tag=tracked_tag,
                    previous_digest=current_digest,
                    target_digest=resolved_digest,
                    next_action="investigate failed digest before retrying deploy",
                    error=failure_message,
                    redaction_secrets=redaction_secrets,
                )
            )
            raise RuntimeError(f"{failure_message}; rollback_succeeded: restored {current_digest}") from exc

        return {
            "result": "deployed",
            "target_digest": resolved_digest,
            "smoke_check": smoke_result,
        }


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

    detail = redact_secret_text(_command_failure_detail(result), secrets=redaction_secrets)
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
            timeout = DEFAULT_DISCORD_WEBHOOK_TIMEOUT
    return DiscordWebhookNotifier(webhook_url, timeout=timeout)


def _send_notification(
    notifier: object | None,
    *,
    event: str,
    tracked_tag: str,
    previous_digest: str,
    target_digest: str,
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
                    f"previous_digest: {previous_digest}",
                    f"target_digest: {target_digest}",
                    f"result: {event}",
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
        "--lock-path",
        type=Path,
        help="advisory lock path; defaults to the deploy env path",
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
            lock_path=args.lock_path,
        )
    except Exception as exc:
        print(f"[deploy-poller] error: {_redact_error(exc, ())}", file=sys.stderr)
        return 1

    print(json.dumps(outcome, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
