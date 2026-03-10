#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import unittest

MOCKED_ACCEPTANCE_MODULES = (
    "tests.test_discord_latest",
    "tests.test_discord_fetch",
    "tests.test_discord_inbound",
    "tests.test_discord_outbound",
    "tests.test_runner",
    "tests.test_check",
    "tests.test_storage",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the mocked acceptance test set aligned to the canonical docs."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the acceptance test modules and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        for module in MOCKED_ACCEPTANCE_MODULES:
            print(module)
        return 0

    suite = unittest.defaultTestLoader.loadTestsFromNames(MOCKED_ACCEPTANCE_MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
