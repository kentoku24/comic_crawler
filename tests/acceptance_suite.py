"""Canonical mocked acceptance suite registry."""

from __future__ import annotations

from tests.acceptance_traceability import ACCEPTANCE_TRACEABILITY

MOCKED_ACCEPTANCE_MODULES = [
    "tests.test_discord_latest",
    "tests.test_discord_fetch",
    "tests.test_discord_inbound",
    "tests.test_discord_outbound",
    "tests.test_runner",
    "tests.test_check",
    "tests.test_storage",
]

TRACEABILITY_CASES = ACCEPTANCE_TRACEABILITY
TRACEABILITY_MODULES = frozenset(
    dotted_path.rsplit(".", 2)[0]
    for entry in ACCEPTANCE_TRACEABILITY.values()
    for dotted_path in entry["tests"]
)
