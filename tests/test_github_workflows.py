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
        self.assertNotIn("environment: production", content.split("  deploy:", maxsplit=1)[1])

    def test_deploy_workflow_emits_and_consumes_an_image_digest(self):
        content = read_workflow("deploy-production.yml")
        service_section = content.split("      - name: Deploy Cloud Run Service", maxsplit=1)[1]

        self.assertIn("image_digest", content)
        self.assertIn("gcloud run jobs update comic-crawler-job", content)
        self.assertIn("gcloud run deploy comic-crawler-service", content)
        self.assertIn("DISCORD_BOT_TOKEN_SECRET_VERSION=${DISCORD_BOT_TOKEN_SECRET_VERSION}", service_section)
        self.assertIn('if [[ "${service_image_ref}" != "${IMAGE_REF}" ]]', content)
        self.assertIn('if [[ "${job_image_ref}" != "${IMAGE_REF}" ]]', content)

    def test_deploy_workflow_verifies_service_and_job_image_refs_from_resource_configs(self):
        content = read_workflow("deploy-production.yml")

        self.assertIn("--format='value(spec.template.spec.containers[0].image)'", content)
        self.assertIn("--format='value(spec.template.spec.template.spec.containers[0].image)'", content)
        self.assertIn('if [[ "${service_image_ref}" != "${IMAGE_REF}" ]]', content)
        self.assertIn('if [[ "${job_image_ref}" != "${IMAGE_REF}" ]]', content)

    def test_deploy_workflow_sets_up_buildx_before_using_gha_cache(self):
        content = read_workflow("deploy-production.yml")

        build_section = content.split("  deploy:", maxsplit=1)[0]

        self.assertIn("uses: docker/setup-buildx-action@v3", build_section)
        self.assertIn("driver: docker-container", build_section)
        self.assertIn("cache-from: type=gha", build_section)
        self.assertIn("cache-to: type=gha,mode=max", build_section)
        self.assertLess(
            build_section.index("uses: docker/setup-buildx-action@v3"),
            build_section.index("uses: docker/build-push-action@v6"),
        )

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

    def test_rollback_workflow_validates_input_without_gcp_auth_and_updates_both_resources_after_gate(self):
        content = read_workflow("rollback-production.yml")
        rollback_service_section = content.split("      - name: Deploy Cloud Run Service", maxsplit=1)[1]

        self.assertIn("asia-northeast1-docker.pkg.dev/star-light-breaker/comic-crawler/comic-crawler@sha256:", content)
        self.assertIn("gcloud run jobs update comic-crawler-job", content)
        self.assertIn("gcloud run deploy comic-crawler-service", content)
        self.assertIn(
            "DISCORD_BOT_TOKEN_SECRET_VERSION=${DISCORD_BOT_TOKEN_SECRET_VERSION}",
            rollback_service_section,
        )
        validate_section = content.split("  rollback:", maxsplit=1)[0]
        self.assertNotIn("Authenticate to Google Cloud", validate_section)
        self.assertNotIn("gcloud artifacts docker images describe", validate_section)
        self.assertIn("gcloud artifacts docker images describe", content.split("  rollback:", maxsplit=1)[1])


if __name__ == "__main__":
    unittest.main()
