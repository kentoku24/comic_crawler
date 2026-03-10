import importlib
import unittest

from tests.acceptance_suite import (
    MOCKED_ACCEPTANCE_MODULES,
    REQUIRED_TRACEABILITY_IDS,
    TRACEABILITY,
)


class AcceptanceSuiteRegistryTests(unittest.TestCase):
    def test_required_contract_ids_are_covered(self):
        self.assertEqual(REQUIRED_TRACEABILITY_IDS, {entry["id"] for entry in TRACEABILITY})

    def test_traceability_entries_reference_modules_in_mocked_suite(self):
        suite_modules = set(MOCKED_ACCEPTANCE_MODULES)
        for entry in TRACEABILITY:
            self.assertTrue(entry["modules"], entry["id"])
            self.assertTrue(set(entry["modules"]).issubset(suite_modules), entry["id"])

    def test_mocked_acceptance_modules_are_importable(self):
        for module_name in MOCKED_ACCEPTANCE_MODULES:
            imported = importlib.import_module(module_name)
            self.assertIsNotNone(imported)
