#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import unittest

from tests.acceptance_suite import MOCKED_ACCEPTANCE_MODULES, TRACEABILITY


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the canonical mocked acceptance suite.")
    parser.add_argument("--list", action="store_true", help="Print suite modules and traceability as JSON.")
    return parser.parse_args()


def build_suite() -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for module_name in MOCKED_ACCEPTANCE_MODULES:
        suite.addTests(loader.loadTestsFromName(module_name))
    return suite


def main() -> int:
    args = parse_args()
    if args.list:
        print(
            json.dumps(
                {
                    "modules": MOCKED_ACCEPTANCE_MODULES,
                    "traceability": TRACEABILITY,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    result = unittest.TextTestRunner(verbosity=2).run(build_suite())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
