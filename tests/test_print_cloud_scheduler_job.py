import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


def load_scheduler_helper_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "print_cloud_scheduler_job.py"
    if not script_path.exists():
        raise AssertionError(f"missing scheduler helper script: {script_path}")

    spec = importlib.util.spec_from_file_location("print_cloud_scheduler_job", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load import spec for: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrintCloudSchedulerJobTests(unittest.TestCase):
    def test_build_run_uri_uses_cloud_run_jobs_run_endpoint(self):
        module = load_scheduler_helper_module()

        self.assertEqual(
            "https://run.googleapis.com/v2/projects/star-light-breaker/locations/asia-northeast1/jobs/comic-crawler-job:run",
            module.build_cloud_run_job_run_uri(
                project="star-light-breaker",
                region="asia-northeast1",
                job_name="comic-crawler-job",
            ),
        )

    def test_build_run_request_body_sets_scheduled_trigger_override(self):
        module = load_scheduler_helper_module()

        self.assertEqual(
            {
                "overrides": {
                    "containerOverrides": [
                        {
                            "env": [
                                {
                                    "name": "MANGA_WATCH_TRIGGER_SOURCE",
                                    "value": "scheduled",
                                }
                            ]
                        }
                    ]
                }
            },
            module.build_run_request_body(),
        )

    def test_build_gcloud_command_for_create_requires_schedule(self):
        module = load_scheduler_helper_module()

        with self.assertRaisesRegex(ValueError, "schedule"):
            module.build_gcloud_scheduler_http_command(action="create")

    def test_build_gcloud_command_for_create_rejects_whitespace_only_schedule(self):
        module = load_scheduler_helper_module()

        with self.assertRaisesRegex(ValueError, "schedule"):
            module.build_gcloud_scheduler_http_command(action="create", schedule="   ")

    def test_build_gcloud_command_for_create_includes_oauth_and_json_body(self):
        module = load_scheduler_helper_module()

        command = module.build_gcloud_scheduler_http_command(
            action="create",
            project="star-light-breaker",
            region="asia-northeast1",
            scheduler_job_name="comic-crawler-scheduled-run",
            cloud_run_job_name="comic-crawler-job",
            oauth_service_account_email="comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com",
            schedule="*/30 * * * *",
            time_zone="Asia/Tokyo",
        )

        self.assertIn("gcloud scheduler jobs create http comic-crawler-scheduled-run", command)
        self.assertIn("--project=star-light-breaker", command)
        self.assertIn("--location=asia-northeast1", command)
        self.assertIn("--schedule='*/30 * * * *'", command)
        self.assertIn("--time-zone=Asia/Tokyo", command)
        self.assertIn("--http-method=POST", command)
        self.assertIn("--oauth-service-account-email=comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com", command)
        self.assertIn("--oauth-token-scope=https://www.googleapis.com/auth/cloud-platform", command)
        self.assertIn(
            "--uri=https://run.googleapis.com/v2/projects/star-light-breaker/locations/asia-northeast1/jobs/comic-crawler-job:run",
            command,
        )
        body_prefix = "--message-body='"
        self.assertIn(body_prefix, command)
        body_json = command.split(body_prefix, 1)[1].rsplit("'", 1)[0]
        self.assertEqual(
            module.build_run_request_body(),
            json.loads(body_json),
        )

    def test_script_prints_update_command_with_canonical_defaults(self):
        repo_root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, "scripts/print_cloud_scheduler_job.py", "update"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("gcloud scheduler jobs update http comic-crawler-scheduled-run", result.stdout)
        self.assertIn("--project=star-light-breaker", result.stdout)
        self.assertIn("--location=asia-northeast1", result.stdout)
        self.assertIn("--http-method=POST", result.stdout)
        self.assertIn(
            "--uri=https://run.googleapis.com/v2/projects/star-light-breaker/locations/asia-northeast1/jobs/comic-crawler-job:run",
            result.stdout,
        )
        self.assertIn(
            "--oauth-service-account-email=comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com",
            result.stdout,
        )

    def test_script_create_requires_schedule_without_traceback(self):
        repo_root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, "scripts/print_cloud_scheduler_job.py", "create"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("--schedule must be a non-empty cron expression", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_script_create_requires_non_empty_schedule_without_traceback(self):
        repo_root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, "scripts/print_cloud_scheduler_job.py", "create", "--schedule", "   "],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("--schedule must be a non-empty cron expression", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
