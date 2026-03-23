import io
import json
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

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


class DeployEnvTests(unittest.TestCase):
    def test_load_deploy_env_reads_required_image_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.deploy"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:abc\n"
                "TZ=Asia/Tokyo\n",
                encoding="utf-8",
            )

            config = deploy_poller.load_deploy_env(env_path)

        self.assertEqual(
            "ghcr.io/kentoku24/comic_crawler@sha256:abc",
            config["COMIC_CRAWLER_IMAGE_REF"],
        )
        self.assertEqual("Asia/Tokyo", config["TZ"])

    def test_render_updated_deploy_env_replaces_only_image_ref(self):
        rendered = deploy_poller.render_updated_deploy_env(
            "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\nTZ=Asia/Tokyo\n",
            "ghcr.io/kentoku24/comic_crawler@sha256:new",
        )

        self.assertIn(
            "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:new\n",
            rendered,
        )
        self.assertIn("TZ=Asia/Tokyo\n", rendered)


class DeployPollerTests(unittest.TestCase):
    def test_run_once_returns_noop_when_env_already_has_resolved_digest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.deploy"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:same\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            runner = FakeCommandRunner()

            result = deploy_poller.run_once(
                tracked_image="ghcr.io/kentoku24/comic_crawler",
                tracked_tag="latest",
                compose_file=compose_file,
                deploy_env_path=env_path,
                resolve_digest=lambda image_ref: "sha256:same",
                command_runner=runner,
            )

        self.assertEqual({"result": "noop", "target_digest": "sha256:same"}, result)
        self.assertEqual([], runner.commands)

    def test_run_once_updates_env_and_runs_deploy_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.deploy"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            lock_path = Path(tmpdir) / "deploy.lock"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n"
                "TZ=Asia/Tokyo\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
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

            result = deploy_poller.run_once(
                tracked_image="ghcr.io/kentoku24/comic_crawler",
                tracked_tag="latest",
                compose_file=compose_file,
                deploy_env_path=env_path,
                lock_path=lock_path,
                resolve_digest=lambda image_ref: "sha256:new",
                command_runner=runner,
            )
            updated_env = env_path.read_text(encoding="utf-8")

        self.assertEqual("deployed", result["result"])
        self.assertEqual("sha256:new", result["target_digest"])
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
        self.assertIn(
            "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:new\n",
            updated_env,
        )

    def test_run_once_rolls_back_to_previous_env_value_when_deploy_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.deploy"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n"
                "MANGA_WATCH_WEBHOOK_URL=https://discord.com/api/webhooks/123/secret\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
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

            with self.assertRaisesRegex(RuntimeError, "rollback_succeeded"):
                deploy_poller.run_once(
                    tracked_image="ghcr.io/kentoku24/comic_crawler",
                    tracked_tag="latest",
                    compose_file=compose_file,
                    deploy_env_path=env_path,
                    resolve_digest=lambda image_ref: "sha256:new",
                    command_runner=runner,
                    notifier=notifier,
                )
            rolled_back_env = env_path.read_text(encoding="utf-8")

        self.assertIn(
            "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:old\n",
            rolled_back_env,
        )
        self.assertEqual(
            ["failed", "rollback_succeeded"],
            [payload["event"] for payload in notifier.sent],
        )

    def test_run_once_uses_deploy_env_lock_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.deploy"
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            env_path.write_text(
                "COMIC_CRAWLER_IMAGE_REF=ghcr.io/kentoku24/comic_crawler@sha256:same\n",
                encoding="utf-8",
            )
            compose_file.write_text("services:\n  comic-crawler:\n    image: ignored\n", encoding="utf-8")
            observed_lock_paths = []

            @contextmanager
            def recording_lock(path):
                observed_lock_paths.append(path)
                yield

            with mock.patch("manga_watch.deploy_poller.advisory_file_lock", side_effect=recording_lock):
                deploy_poller.run_once(
                    tracked_image="ghcr.io/kentoku24/comic_crawler",
                    tracked_tag="latest",
                    compose_file=compose_file,
                    deploy_env_path=env_path,
                    resolve_digest=lambda image_ref: "sha256:same",
                )

        self.assertEqual([str(env_path)], observed_lock_paths)


class DeployPollerCliTests(unittest.TestCase):
    def test_main_help_lists_once_and_lock_path(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exc_info:
                deploy_poller.main(["--help"])

        self.assertEqual(0, exc_info.exception.code)
        help_text = stdout.getvalue()
        self.assertIn("--once", help_text)
        self.assertIn("--lock-path", help_text)
        self.assertNotIn("--dry-run", help_text)
        self.assertNotIn("--state-path", help_text)

    def test_main_calls_run_once_with_cli_arguments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.deploy.yml"
            deploy_env_path = Path(tmpdir) / ".env.deploy"
            lock_path = Path(tmpdir) / "deploy.lock"
            stdout = io.StringIO()

            with mock.patch(
                "manga_watch.deploy_poller.run_once",
                return_value={"result": "noop", "target_digest": "sha256:same"},
            ) as run_once_mock:
                with redirect_stdout(stdout):
                    exit_code = deploy_poller.main(
                        [
                            "--once",
                            "--tracked-image",
                            "ghcr.io/example/comic_crawler",
                            "--tracked-tag",
                            "stable",
                            "--compose-file",
                            str(compose_file),
                            "--deploy-env",
                            str(deploy_env_path),
                            "--lock-path",
                            str(lock_path),
                        ]
                    )

        self.assertEqual(0, exit_code)
        self.assertIn('"result": "noop"', stdout.getvalue())
        run_once_mock.assert_called_once_with(
            tracked_image="ghcr.io/example/comic_crawler",
            tracked_tag="stable",
            compose_file=compose_file,
            deploy_env_path=deploy_env_path,
            lock_path=lock_path,
        )
