from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import requests

from manga_watch.ghcr_registry import resolve_public_tag_digest
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


@dataclass(frozen=True)
class PollPlan:
    action: str
    target_digest: str


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
    del compose_file
    del deploy_env_path
    del command_runner
    del notifier

    resolved_lock_path = lock_path or state_path.with_name(f"{state_path.name}.run")
    tracked_image_ref = build_tracked_image_ref(tracked_image, tracked_tag)

    with advisory_file_lock(str(resolved_lock_path)):
        resolved_digest = resolve_digest(tracked_image_ref)
        if dry_run:
            return {
                "result": "dry_run",
                "tracked_image_ref": tracked_image_ref,
                "target_digest": resolved_digest,
            }

        state = load_poller_state(state_path)
        state["tracked_tag"] = tracked_tag
        state["last_seen_digest"] = resolved_digest
        plan = plan_poll_result(
            tracked_tag=tracked_tag,
            resolved_digest=resolved_digest,
            state=state,
        )

        if plan.action == "noop":
            saved_state = save_poller_state(state_path, state)
            return {
                "result": "noop",
                "state": saved_state,
                "target_digest": resolved_digest,
            }

        state["last_attempted_digest"] = resolved_digest
        state["last_attempt_started_at"] = _utcnow_isoformat()
        saved_state = save_poller_state(state_path, state)
        return {
            "result": "deploy_pending",
            "state": saved_state,
            "target_digest": resolved_digest,
        }


def _utcnow_isoformat() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
