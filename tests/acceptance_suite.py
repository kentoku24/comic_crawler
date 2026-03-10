"""Canonical mocked acceptance suite registry."""

from __future__ import annotations

MOCKED_ACCEPTANCE_MODULES = [
    "tests.test_discord_latest",
    "tests.test_discord_fetch",
    "tests.test_discord_inbound",
    "tests.test_discord_outbound",
    "tests.test_runner",
    "tests.test_check",
]

TRACEABILITY = [
    {
        "id": "latest-query",
        "spec": ["SPEC 6.1", "SPEC 12.2", "doc/受け入れテスト計画書 5.1"],
        "modules": ["tests.test_discord_latest", "tests.test_discord_inbound"],
    },
    {
        "id": "fetch-trigger",
        "spec": ["SPEC 6.2", "SPEC 12.4", "doc/受け入れテスト計画書 5.3"],
        "modules": ["tests.test_discord_fetch", "tests.test_discord_inbound", "tests.test_runner"],
    },
    {
        "id": "daily-notification",
        "spec": ["SPEC 6.3", "SPEC 12.3", "doc/受け入れテスト計画書 5.2"],
        "modules": ["tests.test_discord_outbound", "tests.test_runner", "tests.test_check"],
    },
    {
        "id": "run-report",
        "spec": ["SPEC 6.4", "SPEC 12.5", "doc/受け入れテスト計画書 5.4"],
        "modules": ["tests.test_runner"],
    },
    {
        "id": "state-safety",
        "spec": ["SPEC 7", "SPEC 12.7", "doc/受け入れテスト計画書 5.6"],
        "modules": ["tests.test_runner"],
    },
    {
        "id": "delivery-recovery",
        "spec": ["SPEC 9", "SPEC 12.6", "doc/受け入れテスト計画書 5.5"],
        "modules": ["tests.test_runner", "tests.test_discord_outbound"],
    },
    {
        "id": "security",
        "spec": ["SPEC 10", "SPEC 12.8", "doc/受け入れテスト計画書 5.7"],
        "modules": ["tests.test_runner", "tests.test_discord_outbound"],
    },
]

REQUIRED_TRACEABILITY_IDS = {entry["id"] for entry in TRACEABILITY}
