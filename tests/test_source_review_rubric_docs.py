import unittest
from pathlib import Path


class SourceReviewRubricDocsTests(unittest.TestCase):
    def test_source_expansion_review_rubric_doc_exists_and_is_linked_from_readme(self):
        repo_root = Path(__file__).resolve().parents[1]
        rubric_doc = repo_root / "docs" / "source-expansion-review-rubric.md"
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        rubric_text = rubric_doc.read_text(encoding="utf-8")

        self.assertTrue(rubric_doc.exists())
        self.assertIn("docs/source-expansion-review-rubric.md", readme)
        self.assertIn("# Source Expansion Review Rubric", rubric_text)
        self.assertIn("## Issue review", rubric_text)
        self.assertIn("## PR review", rubric_text)
