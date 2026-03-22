from contextlib import contextmanager
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from manga_watch import deploy_poller


class FakeCommandRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(list(command))
        raise AssertionError("command runner should not be called")


class FakeDiscordNotifier:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


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

    def test_run_once_deploy_pending_persists_attempt_digest_and_timestamp(self):
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
                )

            persisted_state = deploy_poller.load_poller_state(state_path)
            self.assertEqual("deploy_pending", result["result"])
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
