import tempfile
import unittest
from pathlib import Path

from manga_watch import deploy_poller


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
