import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "gh-issue-dependency-spawner"
    / "scripts"
    / "issue_dependency_plan.py"
)
INPUT_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "issue_dependency_plan_epic_6_input.json"
EXPECTED_FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "issue_dependency_plan_epic_6_expected.json"
)


def load_script_module():
    spec = importlib.util.spec_from_file_location("issue_dependency_plan", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class IssueDependencyPlanTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.issue_fixture = json.loads(INPUT_FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.expected_output = json.loads(EXPECTED_FIXTURE_PATH.read_text(encoding="utf-8"))

    def run_script(self, issue_ref: str):
        module = load_script_module()

        def fake_fetch_issue(owner: str, repo: str, number: int) -> dict:
            self.assertEqual("kentoku24", owner)
            self.assertEqual("comic_crawler", repo)
            return self.issue_fixture[str(number)]

        stdout = io.StringIO()
        with mock.patch.object(module, "fetch_issue", side_effect=fake_fetch_issue):
            with mock.patch.object(
                module, "current_repo", return_value="kentoku24/comic_crawler"
            ):
                with mock.patch.object(
                    sys, "argv", ["issue_dependency_plan.py", issue_ref]
                ):
                    with redirect_stdout(stdout):
                        module.main()

        return json.loads(stdout.getvalue())

    def run_script_failure(self, issue_ref: str):
        module = load_script_module()

        def fake_fetch_issue(owner: str, repo: str, number: int) -> dict:
            self.assertEqual("kentoku24", owner)
            self.assertEqual("comic_crawler", repo)
            return self.issue_fixture[str(number)]

        stderr = io.StringIO()
        with mock.patch.object(module, "fetch_issue", side_effect=fake_fetch_issue):
            with mock.patch.object(
                module, "current_repo", return_value="kentoku24/comic_crawler"
            ):
                with mock.patch.object(
                    sys, "argv", ["issue_dependency_plan.py", issue_ref]
                ):
                    with redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as ctx:
                            module.main()

        return ctx.exception.code, stderr.getvalue().strip()

    def test_epic_6_output_matches_expected_value_set(self):
        actual = self.run_script("https://github.com/kentoku24/comic_crawler/issues/6")
        self.assertEqual(self.expected_output, actual)

    def test_epic_6_expected_sets_cover_all_child_issues(self):
        actual = self.run_script("kentoku24/comic_crawler#6")
        actual_children = {item["number"]: item for item in actual["children"]}
        expected_children = {item["number"]: item for item in self.expected_output["children"]}

        self.assertEqual(set(expected_children), set(actual_children))

        for issue_number, expected_child in expected_children.items():
            with self.subTest(issue_number=issue_number):
                self.assertEqual(expected_child, actual_children[issue_number])

    def test_child_issue_inputs_fail_without_child_issue_section(self):
        child_issue_numbers = [7, 8, 21, 11, 9, 10, 12, 13, 16, 17, 18]

        for issue_number in child_issue_numbers:
            with self.subTest(issue_number=issue_number):
                exit_code, stderr = self.run_script_failure(f"#{issue_number}")
                self.assertEqual(1, exit_code)
                self.assertEqual(
                    "could not find a child issue section in the parent issue body",
                    stderr,
                )


if __name__ == "__main__":
    unittest.main()
