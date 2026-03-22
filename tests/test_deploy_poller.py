from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from manga_watch import deploy_poller


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class FakeCommandRunner:
    def __init__(self, *, results=None):
        self.commands = []
        self.results = list(results or [])

    def __call__(self, command):
        self.commands.append(list(command))
        if not self.results:
            raise AssertionError("unexpected command")
        return self.results.pop(0)


class FakeDiscordNotifier:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


class FakeFailingNotifier:
    def __init__(self, message):
        self.message = message
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)
        raise RuntimeError(self.message)


class DeployEnvTests(unittest.TestCase):
    def test_load_deploy_env_reads_image_ref_and_runtime_envs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "deploy.env"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:abc\n"
                "MANGA_WATCH_NOTIFIER_BACKENDS=stdout\n"
                "TZ=Asia/Tokyo\n",
                encoding="utf-8",
            )

            config = deploy_poller.load_deploy_env(env_path)

        self.assertEqual(
            "ghcr.io/kentoku24/comic_crawler@sha256:abc",
            config["COMIC_CRAWLER_IMAGE_REF"],
        )
        self.assertEqual("stdout", config["MANGA_WATCH_NOTIFIER_BACKENDS"])
        self.assertEqual("Asia/Tokyo", config["TZ"])

    def test_render_updated_deploy_env_preserves_unrelated_keys(self):
        before = (
            "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n"
            "TZ=Asia/Tokyo\n"
        )

        after = deploy_poller.render_updated_deploy_env(
            before,
            "ghcr.io/kentoku24/comic_crawler@sha256:new",
        )

        self.assertIn(
            "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:new",
            after,
        )
        self.assertIn("TZ=Asia/Tokyo", after)

    def test_render_updated_deploy_env_replaces_spaced_image_ref_assignment(self):
        before = (
            "COMIC_CRAWLER_IMAGE_REF = ghcr.io/kentoku24/comic_crawler@sha256:old\n"
            "TZ=Asia/Tokyo\n"
        )

        after = deploy_poller.render_updated_deploy_env(
            before,
            "ghcr.io/kentoku24/comic_crawler@sha256:new",
        )

        self.assertEqual(1, after.count("COMIC_CRAWLER_IMAGE_REF="))
        self.assertIn(
            "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:new\n",
            after,
        )
        self.assertNotIn("sha256:old", after)


class PollerStateTests(unittest.TestCase):
    def test_load_poller_state_defaults_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = deploy_poller.load_poller_state(Path(tmpdir) / "missing.json")

        self.assertEqual("latest", state["tracked_tag"])
        self.assertIsNone(state["last_deployed_digest"])

    def test_plan_poll_result_returns_noop_when_digest_matches_last_deployed(self):
        state = {
            "tracked_tag": "latest",
            "last_seen_digest": "sha256:same",
            "last_attempted_digest": "sha256:same",
            "last_deployed_digest": "sha256:same",
            "previous_deployed_digest": None,
            "last_attempt_started_at": None,
            "last_success_at": None,
            "last_error": None,
        }

        plan = deploy_poller.plan_poll_result(
            tracked_tag="latest",
            resolved_digest="sha256:same",
            state=state,
        )

        self.assertEqual("noop", plan.action)

    def test_run_once_dry_run_reports_target_digest_without_touching_env_or_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            lock_path = Path(tmpdir) / "poller.lock"
            env_before = (
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n"
                "TZ=Asia/Tokyo\n"
            )
            state_before = (
                '{\n'
                '  "tracked_tag": "latest",\n'
                '  "last_seen_digest": null,\n'
                '  "last_attempted_digest": null,\n'
                '  "last_deployed_digest": "sha256:old",\n'
                '  "previous_deployed_digest": null,\n'
                '  "last_attempt_started_at": null,\n'
                '  "last_success_at": null,\n'
                '  "last_error": null\n'
                '}\n'
            )
            env_path.write_text(env_before, encoding="utf-8")
            state_path.write_text(state_before, encoding="utf-8")
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            runner = FakeCommandRunner()
            notifier = FakeDiscordNotifier()

            result = deploy_poller.run_once(
                tracked_image="ghcr.io/kentoku24/comic_crawler",
                tracked_tag="latest",
                compose_file=compose_file,
                deploy_env_path=env_path,
                state_path=state_path,
                lock_path=lock_path,
                dry_run=True,
                resolve_digest=lambda image_ref: "sha256:new",
                command_runner=runner,
                notifier=notifier,
            )

            self.assertEqual([], runner.commands)
            self.assertEqual("dry_run", result["result"])
            self.assertEqual("sha256:new", result["target_digest"])
            self.assertEqual(env_before, env_path.read_text(encoding="utf-8"))
            self.assertEqual(state_before, state_path.read_text(encoding="utf-8"))
            self.assertEqual([], notifier.sent)

    def test_run_once_noop_persists_tracked_tag_and_last_seen_without_attempt_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            deploy_poller.save_poller_state(
                state_path,
                {
                    "tracked_tag": "stable",
                    "last_seen_digest": "sha256:old-seen",
                    "last_attempted_digest": None,
                    "last_deployed_digest": "sha256:same",
                    "previous_deployed_digest": None,
                    "last_attempt_started_at": None,
                    "last_success_at": None,
                    "last_error": None,
                },
            )

            result = deploy_poller.run_once(
                tracked_image="ghcr.io/kentoku24/comic_crawler",
                tracked_tag="latest",
                compose_file=compose_file,
                deploy_env_path=env_path,
                state_path=state_path,
                resolve_digest=lambda image_ref: "sha256:same",
            )

            persisted_state = deploy_poller.load_poller_state(state_path)
            self.assertEqual("noop", result["result"])
            self.assertEqual("latest", persisted_state["tracked_tag"])
            self.assertEqual("sha256:same", persisted_state["last_seen_digest"])
            self.assertIsNone(persisted_state["last_attempted_digest"])
            self.assertIsNone(persisted_state["last_attempt_started_at"])

    def test_run_once_deployed_persists_attempt_digest_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            deploy_poller.save_poller_state(
                state_path,
                {
                    "tracked_tag": "latest",
                    "last_seen_digest": "sha256:old-seen",
                    "last_attempted_digest": None,
                    "last_deployed_digest": "sha256:old",
                    "previous_deployed_digest": None,
                    "last_attempt_started_at": None,
                    "last_success_at": None,
                    "last_error": None,
                },
            )
            runner = FakeCommandRunner(
                results=[
                    CommandResult(0, "", ""),
                    CommandResult(0, "", ""),
                    CommandResult(
                        0,
                        json.dumps([{"Service": "comic-crawler", "State": "running"}]),
                        "",
                    ),
                    CommandResult(0, '{"summary": {"monitored_work_count": 1}}', ""),
                ]
            )

            with mock.patch(
                "manga_watch.deploy_poller._utcnow_isoformat",
                return_value="2026-03-22T00:00:00Z",
            ):
                result = deploy_poller.run_once(
                    tracked_image="ghcr.io/kentoku24/comic_crawler",
                    tracked_tag="latest",
                    compose_file=compose_file,
                    deploy_env_path=env_path,
                    state_path=state_path,
                    resolve_digest=lambda image_ref: "sha256:new",
                    command_runner=runner,
                )

            persisted_state = deploy_poller.load_poller_state(state_path)
            self.assertEqual("deployed", result["result"])
            self.assertEqual("sha256:new", persisted_state["last_attempted_digest"])
            self.assertEqual("2026-03-22T00:00:00Z", persisted_state["last_attempt_started_at"])

    def test_run_once_uses_resolved_top_level_lock_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            observed_lock_paths = []

            @contextmanager
            def recording_lock(path):
                observed_lock_paths.append(path)
                yield

            with mock.patch("manga_watch.deploy_poller.advisory_file_lock", side_effect=recording_lock):
                result = deploy_poller.run_once(
                    tracked_image="ghcr.io/kentoku24/comic_crawler",
                    tracked_tag="latest",
                    compose_file=compose_file,
                    deploy_env_path=env_path,
                    state_path=state_path,
                    dry_run=True,
                    resolve_digest=lambda image_ref: "sha256:new",
                )

            expected_lock_path = state_path.with_name(f"{state_path.name}.run")
            self.assertEqual("dry_run", result["result"])
            self.assertEqual([str(expected_lock_path)], observed_lock_paths)

    def test_run_once_uses_explicit_lock_path_verbatim(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            explicit_lock_path = Path(tmpdir) / "custom.lock"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            observed_lock_paths = []

            @contextmanager
            def recording_lock(path):
                observed_lock_paths.append(path)
                yield

            with mock.patch("manga_watch.deploy_poller.advisory_file_lock", side_effect=recording_lock):
                result = deploy_poller.run_once(
                    tracked_image="ghcr.io/kentoku24/comic_crawler",
                    tracked_tag="latest",
                    compose_file=compose_file,
                    deploy_env_path=env_path,
                    state_path=state_path,
                    lock_path=explicit_lock_path,
                    dry_run=True,
                    resolve_digest=lambda image_ref: "sha256:new",
                )

            self.assertEqual("dry_run", result["result"])
            self.assertEqual([str(explicit_lock_path)], observed_lock_paths)


class DeployExecutionTests(unittest.TestCase):
    def test_run_once_updates_env_then_runs_pull_up_ps_and_smoke_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            lock_path = Path(tmpdir) / "poller.lock"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n"
                "TZ=Asia/Tokyo\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            deploy_poller.save_poller_state(
                state_path,
                {
                    "tracked_tag": "latest",
                    "last_seen_digest": "sha256:old",
                    "last_attempted_digest": None,
                    "last_deployed_digest": "sha256:old",
                    "previous_deployed_digest": None,
                    "last_attempt_started_at": None,
                    "last_success_at": None,
                    "last_error": "stale error",
                },
            )
            runner = FakeCommandRunner(
                results=[
                    CommandResult(0, "", ""),
                    CommandResult(0, "", ""),
                    CommandResult(
                        0,
                        json.dumps([{"Service": "comic-crawler", "State": "running"}]),
                        "",
                    ),
                    CommandResult(0, '{"summary": {"monitored_work_count": 1}}', ""),
                ]
            )
            notifier = FakeDiscordNotifier()

            with mock.patch(
                "manga_watch.deploy_poller._utcnow_isoformat",
                return_value="2026-03-22T00:00:00Z",
            ):
                result = deploy_poller.run_once(
                    tracked_image="ghcr.io/kentoku24/comic_crawler",
                    tracked_tag="latest",
                    compose_file=compose_file,
                    deploy_env_path=env_path,
                    state_path=state_path,
                    lock_path=lock_path,
                    resolve_digest=lambda image_ref: "sha256:new",
                    command_runner=runner,
                    notifier=notifier,
                )

            self.assertEqual(
                [
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "pull",
                        "comic-crawler",
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "up",
                        "-d",
                        "comic-crawler",
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "ps",
                        "--format",
                        "json",
                        "comic-crawler",
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "exec",
                        "-T",
                        "comic-crawler",
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
                    ],
                ],
                runner.commands,
            )
            self.assertEqual("deployed", result["result"])
            self.assertIn(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:new\n",
                env_path.read_text(encoding="utf-8"),
            )
            persisted_state = deploy_poller.load_poller_state(state_path)
            self.assertEqual("sha256:new", persisted_state["last_deployed_digest"])
            self.assertEqual("sha256:old", persisted_state["previous_deployed_digest"])
            self.assertEqual("2026-03-22T00:00:00Z", persisted_state["last_success_at"])
            self.assertIsNone(persisted_state["last_error"])
            self.assertEqual(
                ["detected", "deployed"],
                [payload["event"] for payload in notifier.sent],
            )

    def test_run_once_rolls_back_once_when_smoke_check_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            deploy_poller.save_poller_state(
                state_path,
                {
                    "tracked_tag": "latest",
                    "last_seen_digest": "sha256:old",
                    "last_attempted_digest": None,
                    "last_deployed_digest": "sha256:old",
                    "previous_deployed_digest": "sha256:prev",
                    "last_attempt_started_at": None,
                    "last_success_at": "2026-03-21T00:00:00Z",
                    "last_error": None,
                },
            )
            runner = FakeCommandRunner(
                results=[
                    CommandResult(0, "", ""),
                    CommandResult(0, "", ""),
                    CommandResult(
                        0,
                        json.dumps([{"Service": "comic-crawler", "State": "running"}]),
                        "",
                    ),
                    CommandResult(1, "", "smoke failed"),
                    CommandResult(0, "", ""),
                    CommandResult(
                        0,
                        json.dumps([{"Service": "comic-crawler", "State": "running"}]),
                        "",
                    ),
                    CommandResult(0, '{"summary": {"monitored_work_count": 1}}', ""),
                ]
            )
            notifier = FakeDiscordNotifier()

            with mock.patch(
                "manga_watch.deploy_poller._utcnow_isoformat",
                return_value="2026-03-22T00:00:00Z",
            ):
                with self.assertRaisesRegex(RuntimeError, "rollback_succeeded"):
                    deploy_poller.run_once(
                        tracked_image="ghcr.io/kentoku24/comic_crawler",
                        tracked_tag="latest",
                        compose_file=compose_file,
                        deploy_env_path=env_path,
                        state_path=state_path,
                        resolve_digest=lambda image_ref: "sha256:new",
                        command_runner=runner,
                        notifier=notifier,
                    )

            self.assertEqual(
                [
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "pull",
                        "comic-crawler",
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "up",
                        "-d",
                        "comic-crawler",
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "ps",
                        "--format",
                        "json",
                        "comic-crawler",
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "exec",
                        "-T",
                        "comic-crawler",
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
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "up",
                        "-d",
                        "comic-crawler",
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "ps",
                        "--format",
                        "json",
                        "comic-crawler",
                    ],
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "--env-file",
                        str(env_path),
                        "exec",
                        "-T",
                        "comic-crawler",
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
                    ],
                ],
                runner.commands,
            )
            self.assertIn(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n",
                env_path.read_text(encoding="utf-8"),
            )
            persisted_state = deploy_poller.load_poller_state(state_path)
            self.assertEqual("sha256:new", persisted_state["last_attempted_digest"])
            self.assertEqual("sha256:old", persisted_state["last_deployed_digest"])
            self.assertEqual("sha256:prev", persisted_state["previous_deployed_digest"])
            self.assertIn("smoke failed", persisted_state["last_error"])
            self.assertEqual(
                ["detected", "failed", "rollback_succeeded"],
                [payload["event"] for payload in notifier.sent],
            )

    def test_run_once_notification_failures_do_not_block_successful_deploy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            webhook_url = "https://discord.com/api/webhooks/123/secret"
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n"
                f"MANGA_WATCH_WEBHOOK_URL={webhook_url}\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            deploy_poller.save_poller_state(
                state_path,
                {
                    "tracked_tag": "latest",
                    "last_seen_digest": "sha256:old",
                    "last_attempted_digest": None,
                    "last_deployed_digest": "sha256:old",
                    "previous_deployed_digest": None,
                    "last_attempt_started_at": None,
                    "last_success_at": None,
                    "last_error": None,
                },
            )
            runner = FakeCommandRunner(
                results=[
                    CommandResult(0, "", ""),
                    CommandResult(0, "", ""),
                    CommandResult(
                        0,
                        json.dumps([{"Service": "comic-crawler", "State": "running"}]),
                        "",
                    ),
                    CommandResult(0, '{"summary": {"monitored_work_count": 1}}', ""),
                ]
            )
            notifier = FakeFailingNotifier(f"notify failed: {webhook_url}")

            with mock.patch(
                "manga_watch.deploy_poller._utcnow_isoformat",
                return_value="2026-03-22T00:00:00Z",
            ):
                result = deploy_poller.run_once(
                    tracked_image="ghcr.io/kentoku24/comic_crawler",
                    tracked_tag="latest",
                    compose_file=compose_file,
                    deploy_env_path=env_path,
                    state_path=state_path,
                    resolve_digest=lambda image_ref: "sha256:new",
                    command_runner=runner,
                    notifier=notifier,
                )

            self.assertEqual("deployed", result["result"])
            self.assertEqual(["detected", "deployed"], [payload["event"] for payload in notifier.sent])
            for payload in notifier.sent:
                self.assertNotIn(webhook_url, payload["content"])

    def test_run_once_notification_failures_do_not_block_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            webhook_url = "https://discord.com/api/webhooks/123/secret"
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n"
                f"MANGA_WATCH_WEBHOOK_URL={webhook_url}\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            deploy_poller.save_poller_state(
                state_path,
                {
                    "tracked_tag": "latest",
                    "last_seen_digest": "sha256:old",
                    "last_attempted_digest": None,
                    "last_deployed_digest": "sha256:old",
                    "previous_deployed_digest": "sha256:prev",
                    "last_attempt_started_at": None,
                    "last_success_at": None,
                    "last_error": None,
                },
            )
            runner = FakeCommandRunner(
                results=[
                    CommandResult(0, "", ""),
                    CommandResult(0, "", ""),
                    CommandResult(
                        0,
                        json.dumps([{"Service": "comic-crawler", "State": "running"}]),
                        "",
                    ),
                    CommandResult(1, "", "smoke failed"),
                    CommandResult(0, "", ""),
                    CommandResult(
                        0,
                        json.dumps([{"Service": "comic-crawler", "State": "running"}]),
                        "",
                    ),
                    CommandResult(0, '{"summary": {"monitored_work_count": 1}}', ""),
                ]
            )
            notifier = FakeFailingNotifier(f"notify failed: {webhook_url}")

            with mock.patch(
                "manga_watch.deploy_poller._utcnow_isoformat",
                return_value="2026-03-22T00:00:00Z",
            ):
                with self.assertRaisesRegex(RuntimeError, "rollback_succeeded"):
                    deploy_poller.run_once(
                        tracked_image="ghcr.io/kentoku24/comic_crawler",
                        tracked_tag="latest",
                        compose_file=compose_file,
                        deploy_env_path=env_path,
                        state_path=state_path,
                        resolve_digest=lambda image_ref: "sha256:new",
                        command_runner=runner,
                        notifier=notifier,
                    )

            self.assertEqual(
                ["detected", "failed", "rollback_succeeded"],
                [payload["event"] for payload in notifier.sent],
            )

    def test_run_once_redacts_webhook_url_in_failure_state_exception_and_notifications(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            webhook_url = "https://discord.com/api/webhooks/123/secret"
            env_path = Path(tmpdir) / "deploy.env"
            state_path = Path(tmpdir) / "poller-state.json"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n"
                f"MANGA_WATCH_WEBHOOK_URL={webhook_url}\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            deploy_poller.save_poller_state(
                state_path,
                {
                    "tracked_tag": "latest",
                    "last_seen_digest": "sha256:old",
                    "last_attempted_digest": None,
                    "last_deployed_digest": "sha256:old",
                    "previous_deployed_digest": "sha256:prev",
                    "last_attempt_started_at": None,
                    "last_success_at": None,
                    "last_error": None,
                },
            )
            runner = FakeCommandRunner(
                results=[
                    CommandResult(0, "", ""),
                    CommandResult(0, "", ""),
                    CommandResult(
                        0,
                        json.dumps([{"Service": "comic-crawler", "State": "running"}]),
                        "",
                    ),
                    CommandResult(1, "", f"smoke failed: {webhook_url}"),
                    CommandResult(1, "", f"rollback failed: {webhook_url}"),
                ]
            )
            notifier = FakeDiscordNotifier()

            with mock.patch(
                "manga_watch.deploy_poller._utcnow_isoformat",
                return_value="2026-03-22T00:00:00Z",
            ):
                with self.assertRaises(RuntimeError) as exc_info:
                    deploy_poller.run_once(
                        tracked_image="ghcr.io/kentoku24/comic_crawler",
                        tracked_tag="latest",
                        compose_file=compose_file,
                        deploy_env_path=env_path,
                        state_path=state_path,
                        resolve_digest=lambda image_ref: "sha256:new",
                        command_runner=runner,
                        notifier=notifier,
                    )

            persisted_state = deploy_poller.load_poller_state(state_path)
            self.assertNotIn(webhook_url, persisted_state["last_error"])
            self.assertIn("[REDACTED_WEBHOOK_URL]", persisted_state["last_error"])
            self.assertNotIn(webhook_url, str(exc_info.exception))
            self.assertIn("[REDACTED_WEBHOOK_URL]", str(exc_info.exception))
            self.assertTrue(notifier.sent)
            for payload in notifier.sent:
                self.assertNotIn(webhook_url, payload["content"])
            self.assertEqual("rollback_failed", notifier.sent[-1]["event"])


class DeployPollerCliTests(unittest.TestCase):
    def test_main_help_lists_once_and_dry_run(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exc_info:
                deploy_poller.main(["--help"])

        self.assertEqual(0, exc_info.exception.code)
        help_text = stdout.getvalue()
        normalized_help_text = " ".join(help_text.split())
        normalized_help_text = normalized_help_text.replace("<state- path>", "<state-path>")
        self.assertIn("--once", help_text)
        self.assertIn("--dry-run", help_text)
        self.assertIn("advisory lock path prefix", normalized_help_text)
        self.assertIn("appends .lock", normalized_help_text)
        self.assertIn("defaults to <state-path>.run", normalized_help_text.lower())

    def test_main_with_once_and_dry_run_calls_run_once_with_cli_arguments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            deploy_env_path = Path(tmpdir) / ".env.deploy"
            state_path = Path(tmpdir) / "ghcr-poller-state.json"
            lock_path = Path(tmpdir) / "ghcr-poller.lock"
            stdout = io.StringIO()

            with mock.patch(
                "manga_watch.deploy_poller.run_once",
                return_value={"result": "dry_run", "target_digest": "sha256:new"},
            ) as run_once_mock:
                with redirect_stdout(stdout):
                    exit_code = deploy_poller.main(
                        [
                            "--once",
                            "--dry-run",
                            "--tracked-image",
                            "ghcr.io/example/comic_crawler",
                            "--tracked-tag",
                            "stable",
                            "--compose-file",
                            str(compose_file),
                            "--deploy-env",
                            str(deploy_env_path),
                            "--state-path",
                            str(state_path),
                            "--lock-path",
                            str(lock_path),
                        ]
                    )

        self.assertEqual(0, exit_code)
        self.assertIn('"result": "dry_run"', stdout.getvalue())
        run_once_mock.assert_called_once_with(
            tracked_image="ghcr.io/example/comic_crawler",
            tracked_tag="stable",
            compose_file=compose_file,
            deploy_env_path=deploy_env_path,
            state_path=state_path,
            lock_path=lock_path,
            dry_run=True,
        )
