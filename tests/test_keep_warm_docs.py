import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "README.md"
GCP_DEPLOY_PATH = ROOT / "doc" / "gcp-deploy.md"


class KeepWarmDocsTests(unittest.TestCase):
    def test_readme_recommends_five_minute_healthz_ping(self):
        readme = README_PATH.read_text(encoding="utf-8")

        self.assertIn("5` 分おき", readme)
        self.assertNotIn("15` 分おき", readme)

    def test_gcp_deploy_doc_uses_five_minute_keep_warm_schedule(self):
        gcp_deploy = GCP_DEPLOY_PATH.read_text(encoding="utf-8")

        self.assertIn("--schedule='*/5 * * * *'", gcp_deploy)
        self.assertIn("初期値は 5 分間隔", gcp_deploy)
        self.assertNotIn("--schedule='*/15 * * * *'", gcp_deploy)
        self.assertNotIn("初期値は 15 分間隔", gcp_deploy)


if __name__ == "__main__":
    unittest.main()
