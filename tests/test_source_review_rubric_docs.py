import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "README.md"
RUBRIC_PATH = ROOT / "docs" / "source-expansion-review-rubric.md"


class SourceReviewRubricDocsTests(unittest.TestCase):
    def test_rubric_doc_exists(self):
        self.assertTrue(
            RUBRIC_PATH.exists(),
            msg="docs/source-expansion-review-rubric.md must exist for source expansion review guidance",
        )

    def test_readme_links_to_rubric_doc(self):
        readme = README_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "docs/source-expansion-review-rubric.md",
            readme,
            msg="README.md must link to the source expansion review rubric from the source adapter guide",
        )

    def test_rubric_doc_covers_issue_and_pr_review_bars(self):
        rubric = RUBRIC_PATH.read_text(encoding="utf-8")

        required_sections = (
            "## Issue review rubric",
            "### Scope clarity",
            "### Public-surface legitimacy",
            "### Testability before implementation",
            "### Issue approval bar",
            "## PR review rubric",
            "### Architecture fit",
            "### Test evidence quality",
            "### Regression safety",
            "### PR approval bar",
            "## Recommended issue sections",
            "## Recommended PR sections",
        )

        for section in required_sections:
            self.assertIn(section, rubric)


if __name__ == "__main__":
    unittest.main()
