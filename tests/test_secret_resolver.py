import os
import unittest
from unittest import mock

from manga_watch.discord_outbound import DiscordOutboundConfig
from manga_watch.notifier import NotifierConfig
from manga_watch.secret_resolver import resolve_env_value


class FakeSecretPayload:
    def __init__(self, text):
        self.data = text.encode("utf-8")


class FakeSecretResponse:
    def __init__(self, text):
        self.payload = FakeSecretPayload(text)


class FakeSecretManagerClient:
    def __init__(self, payloads):
        self.payloads = dict(payloads)
        self.requests = []

    def access_secret_version(self, request):
        name = request["name"] if isinstance(request, dict) else request
        self.requests.append(name)
        if name not in self.payloads:
            raise AssertionError(f"unexpected secret lookup: {name}")
        return FakeSecretResponse(self.payloads[name])


class SecretResolverTests(unittest.TestCase):
    def test_resolve_env_value_prefers_direct_env_value(self):
        client = FakeSecretManagerClient(
            {"projects/demo/secrets/discord-bot-token/versions/latest": "from-secret-manager"}
        )

        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "from-env",
                "DISCORD_BOT_TOKEN_SECRET_VERSION": "projects/demo/secrets/discord-bot-token/versions/latest",
            },
            clear=False,
        ):
            value = resolve_env_value("DISCORD_BOT_TOKEN", client=client)

        self.assertEqual("from-env", value)
        self.assertEqual([], client.requests)

    def test_resolve_env_value_uses_secret_manager_version_when_direct_value_missing(self):
        client = FakeSecretManagerClient(
            {"projects/demo/secrets/discord-bot-token/versions/latest": "from-secret-manager"}
        )

        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN_SECRET_VERSION": "projects/demo/secrets/discord-bot-token/versions/latest",
            },
            clear=True,
        ):
            value = resolve_env_value("DISCORD_BOT_TOKEN", client=client)

        self.assertEqual("from-secret-manager", value)
        self.assertEqual(
            ["projects/demo/secrets/discord-bot-token/versions/latest"],
            client.requests,
        )

    def test_notifier_config_from_env_resolves_webhook_secret_version(self):
        client = FakeSecretManagerClient(
            {"projects/demo/secrets/webhook/versions/latest": "https://example.com/secret-webhook"}
        )
        with mock.patch.dict(
            os.environ,
            {
                "MANGA_WATCH_NOTIFIER_BACKENDS": "stdout,webhook",
                "MANGA_WATCH_WEBHOOK_URL_SECRET_VERSION": "projects/demo/secrets/webhook/versions/latest",
            },
            clear=True,
        ):
            with mock.patch(
                "manga_watch.secret_resolver.build_secret_manager_client",
                return_value=client,
            ):
                config = NotifierConfig.from_env()

        self.assertEqual(("stdout", "webhook"), config.backends)
        self.assertEqual("https://example.com/secret-webhook", config.webhook_url)

    def test_discord_outbound_config_from_env_resolves_bot_token_secret_version(self):
        client = FakeSecretManagerClient(
            {"projects/demo/secrets/discord-bot-token/versions/latest": "discord-secret-token"}
        )
        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN_SECRET_VERSION": "projects/demo/secrets/discord-bot-token/versions/latest",
                "DISCORD_MAIN_CHANNEL_ID": "main-channel",
                "DISCORD_RUN_REPORT_CHANNEL_ID": "run-report-channel",
            },
            clear=True,
        ):
            with mock.patch(
                "manga_watch.secret_resolver.build_secret_manager_client",
                return_value=client,
            ):
                config = DiscordOutboundConfig.from_env()

        self.assertEqual("discord-secret-token", config.bot_token)
        self.assertEqual("main-channel", config.main_channel_id)
        self.assertEqual("run-report-channel", config.run_report_channel_id)
