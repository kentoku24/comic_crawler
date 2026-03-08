import unittest

from manga_watch.discord_fetch import handle_fetch_trigger
from manga_watch.runner import (
    FETCH_ACCEPTED_MESSAGE,
    TRIGGER_SOURCE_DISCORD_FETCH,
)


class RecordingCoordinator:
    def __init__(self, outcome):
        self.outcome = dict(outcome)
        self.calls = []

    def start_background(self, trigger_source):
        self.calls.append(trigger_source)
        return dict(self.outcome)


class DiscordFetchTests(unittest.TestCase):
    def test_handle_fetch_trigger_routes_only_trimmed_exact_fetch(self):
        coordinator = RecordingCoordinator(
            {
                "ok": True,
                "accepted": True,
                "background": True,
                "timestamp": "2026-03-08 00:00:00 JST",
                "triggerSource": TRIGGER_SOURCE_DISCORD_FETCH,
            }
        )

        response = handle_fetch_trigger("fetch", coordinator=coordinator)

        self.assertEqual([TRIGGER_SOURCE_DISCORD_FETCH], coordinator.calls)
        self.assertIsNotNone(response)
        self.assertTrue(response["accepted"])
        self.assertEqual(FETCH_ACCEPTED_MESSAGE, response["message"])
        self.assertEqual(TRIGGER_SOURCE_DISCORD_FETCH, response["triggerSource"])
        self.assertIsNone(handle_fetch_trigger("fetch now", coordinator=coordinator))
        self.assertEqual([TRIGGER_SOURCE_DISCORD_FETCH], coordinator.calls)

    def test_handle_fetch_trigger_accepts_whitespace_trimmed_fetch(self):
        coordinator = RecordingCoordinator(
            {
                "ok": True,
                "accepted": True,
                "background": True,
                "timestamp": "2026-03-08 00:00:00 JST",
                "triggerSource": TRIGGER_SOURCE_DISCORD_FETCH,
            }
        )

        response = handle_fetch_trigger("  fetch  ", coordinator=coordinator)

        self.assertEqual([TRIGGER_SOURCE_DISCORD_FETCH], coordinator.calls)
        self.assertIsNotNone(response)
        self.assertEqual(FETCH_ACCEPTED_MESSAGE, response["message"])
