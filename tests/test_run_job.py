import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.run_job import job_trigger_source_from_env
from manga_watch.runner import TRIGGER_SOURCE_DISCORD_FETCH, TRIGGER_SOURCE_SCHEDULED


class RunJobTests(unittest.TestCase):
    def test_job_trigger_source_defaults_to_scheduled(self):
        self.assertEqual(TRIGGER_SOURCE_SCHEDULED, job_trigger_source_from_env({}))

    def test_job_trigger_source_maps_manual_aliases_to_discord_fetch(self):
        self.assertEqual(
            TRIGGER_SOURCE_DISCORD_FETCH,
            job_trigger_source_from_env({"MANGA_WATCH_TRIGGER_SOURCE": "manual"}),
        )
        self.assertEqual(
            TRIGGER_SOURCE_DISCORD_FETCH,
            job_trigger_source_from_env({"MANGA_WATCH_TRIGGER_SOURCE": "fetch"}),
        )

    def test_run_job_module_runs_until_config_validation(self):
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("MANGA_WATCH_NOTIFIER_BACKENDS", None)
        env.pop("DISCORD_BOT_TOKEN", None)
        env.pop("DISCORD_BOT_TOKEN_SECRET_VERSION", None)

        result = subprocess.run(
            [sys.executable, "-m", "manga_watch.run_job"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("[run_job] configuration error:", result.stderr)

