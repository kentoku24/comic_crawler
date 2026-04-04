import unittest
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_workflow(name: str) -> str:
    workflow_path = repo_root() / ".github" / "workflows" / name
    if not workflow_path.exists():
        raise AssertionError(f"missing workflow: {workflow_path}")
    return workflow_path.read_text(encoding="utf-8")


class GitHubWorkflowContractTests(unittest.TestCase):
    def test_deploy_workflow_exists_and_targets_main_push(self):
        content = read_workflow("deploy-production.yml")

        self.assertIn("on:", content)
        self.assertIn("push:", content)
        self.assertIn("branches:", content)
        self.assertIn("- main", content)

    def test_deploy_workflow_defines_test_build_and_deploy_jobs(self):
        content = read_workflow("deploy-production.yml")

        self.assertIn("jobs:", content)
        self.assertIn("test:", content)
        self.assertIn("build:", content)
        self.assertIn("deploy:", content)
        self.assertIn("environment: production", content)

    def test_deploy_workflow_emits_and_consumes_an_image_digest(self):
        content = read_workflow("deploy-production.yml")

        self.assertIn("image_digest", content)
        self.assertIn("gcloud run jobs update comic-crawler-job", content)
        self.assertIn("gcloud run deploy comic-crawler-service", content)

    def test_rollback_workflow_exists_and_uses_workflow_dispatch(self):
        content = read_workflow("rollback-production.yml")

        self.assertIn("on:", content)
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("image_ref:", content)

    def test_rollback_workflow_defines_validate_and_rollback_jobs(self):
        content = read_workflow("rollback-production.yml")

        self.assertIn("jobs:", content)
        self.assertIn("validate:", content)
        self.assertIn("rollback:", content)
        self.assertIn("environment: production", content)

    def test_rollback_workflow_validates_input_and_updates_both_resources(self):
        content = read_workflow("rollback-production.yml")

        self.assertIn("asia-northeast1-docker.pkg.dev/star-light-breaker/comic-crawler/comic-crawler@sha256:", content)
        self.assertIn("gcloud artifacts docker images describe", content)
        self.assertIn("gcloud run jobs update comic-crawler-job", content)
        self.assertIn("gcloud run deploy comic-crawler-service", content)


if __name__ == "__main__":
    unittest.main()
