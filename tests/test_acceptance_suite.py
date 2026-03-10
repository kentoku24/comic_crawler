import importlib
import unittest

from tests.acceptance_suite import (
    MOCKED_ACCEPTANCE_MODULES,
    TRACEABILITY_CASES,
    TRACEABILITY_MODULES,
)


class AcceptanceSuiteRegistryTests(unittest.TestCase):
    def test_traceability_modules_match_mocked_suite(self):
        self.assertEqual(set(MOCKED_ACCEPTANCE_MODULES), set(TRACEABILITY_MODULES))

    def test_traceability_manifest_is_non_empty(self):
        self.assertTrue(TRACEABILITY_CASES)

    def test_mocked_acceptance_modules_are_importable(self):
        for module_name in MOCKED_ACCEPTANCE_MODULES:
            imported = importlib.import_module(module_name)
            self.assertIsNotNone(imported)
