import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


def load_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "print_keep_warm_scheduler_job.py"
    spec = importlib.util.spec_from_file_location("print_keep_warm_scheduler_job", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load keep warm script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrintKeepWarmSchedulerJobTests(unittest.TestCase):
    def test_default_schedule_is_five_minutes(self):
        module = load_module()
        self.assertEqual("*/5 * * * *", module.DEFAULT_SCHEDULE)

    def test_build_command_uses_healthz_and_get(self):
        module = load_module()
        command = module.build_gcloud_scheduler_keep_warm_command(
            action="create",
            service_url="https://comic-crawler-service-abc.a.run.app",
        )
        self.assertIn("gcloud scheduler jobs create http comic-crawler-service-keep-warm", command)
        self.assertIn("--schedule='*/5 * * * *'", command)
        self.assertIn("--uri=https://comic-crawler-service-abc.a.run.app/healthz", command)
        self.assertIn("--http-method=GET", command)

    def test_main_rejects_blank_schedule(self):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/print_keep_warm_scheduler_job.py",
                "create",
                "--service-url",
                "https://example.com",
                "--schedule",
                "   ",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("--schedule must be a non-empty cron expression", result.stderr)


if __name__ == "__main__":
    unittest.main()
