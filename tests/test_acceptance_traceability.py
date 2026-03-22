from __future__ import annotations

import importlib
import unittest

from tests.acceptance_traceability import ACCEPTANCE_TRACEABILITY


EXPECTED_MOCKED_CASE_IDS = {
    "TC-LATEST-01",
    "TC-LATEST-02",
    "TC-LATEST-03",
    "TC-LATEST-04",
    "TC-LATEST-05",
    "TC-LATEST-06",
    "TC-LATEST-07",
    "TC-LATEST-08",
    "TC-LATEST-09",
    "TC-LATEST-10",
    "TC-LATEST-11",
    "TC-LATEST-12",
    "TC-DAILY-01",
    "TC-DAILY-02",
    "TC-DAILY-03",
    "TC-DAILY-04",
    "TC-DAILY-05",
    "TC-DAILY-06",
    "TC-DAILY-07",
    "TC-DAILY-08",
    "TC-DAILY-09",
    "TC-DAILY-10",
    "TC-FETCH-01",
    "TC-FETCH-02",
    "TC-FETCH-03",
    "TC-FETCH-04",
    "TC-REPORT-01",
    "TC-REPORT-02",
    "TC-REPORT-03",
    "TC-REPORT-04",
    "TC-DELIVERY-01",
    "TC-DELIVERY-02",
    "TC-DELIVERY-03",
    "TC-DELIVERY-04",
    "TC-STATE-01",
    "TC-STATE-02",
    "TC-STATE-03",
    "TC-SEC-01",
    "TC-SEC-02",
    "TC-SEC-03",
}

VALID_LAYERS = {
    "formatter",
    "mocked_discord_integration",
    "orchestration",
    "persistence",
    "security",
}


class AcceptanceTraceabilityTests(unittest.TestCase):
    def test_manifest_covers_mocked_acceptance_cases(self):
        self.assertEqual(EXPECTED_MOCKED_CASE_IDS, set(ACCEPTANCE_TRACEABILITY))

    def test_manifest_uses_known_layers(self):
        for case_id, entry in ACCEPTANCE_TRACEABILITY.items():
            self.assertIn(entry["layer"], VALID_LAYERS, case_id)

    def test_manifest_points_to_existing_tests(self):
        for case_id, entry in ACCEPTANCE_TRACEABILITY.items():
            self.assertTrue(entry["tests"], case_id)
            for dotted_path in entry["tests"]:
                module_name, class_name, method_name = dotted_path.rsplit(".", 2)
                module = importlib.import_module(module_name)
                klass = getattr(module, class_name)
                self.assertTrue(issubclass(klass, unittest.TestCase), dotted_path)
                self.assertTrue(hasattr(klass, method_name), dotted_path)
