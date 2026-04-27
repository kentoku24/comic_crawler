import os
import unittest
from unittest import mock

from manga_watch.discord_fetch import FETCH_COMMAND
from manga_watch.discord_latest import LATEST_COMMAND
from manga_watch.discord_remove import REMOVE_COMMAND
from manga_watch.discord_search import SEARCH_COMMAND
from manga_watch.discord_supertwins_manage import SUPERTWINS_MANAGE_COMMAND
from manga_watch.discord_supertwins_search import SUPERTWINS_SEARCH_COMMAND
from manga_watch.discord_where import WHERE_COMMAND


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        return self._json_data


class FakeRequestsSession:
    def __init__(self, get_responses=None, put_responses=None):
        self.get_responses = list(get_responses or [])
        self.put_responses = list(put_responses or [])
        self.get_calls = []
        self.put_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        if not self.get_responses:
            raise AssertionError("unexpected GET")
        return self.get_responses.pop(0)

    def put(self, url, **kwargs):
        self.put_calls.append({"url": url, **kwargs})
        if not self.put_responses:
            raise AssertionError("unexpected PUT")
        return self.put_responses.pop(0)


class DiscordCommandRegistrationTests(unittest.TestCase):
    def test_default_command_definitions_include_supertwins_commands(self):
        from manga_watch.discord_command_registration import default_interaction_commands

        commands = default_interaction_commands()

        self.assertEqual(
            [
                LATEST_COMMAND,
                FETCH_COMMAND,
                "add",
                SEARCH_COMMAND,
                WHERE_COMMAND,
                REMOVE_COMMAND,
                SUPERTWINS_SEARCH_COMMAND,
                SUPERTWINS_MANAGE_COMMAND,
            ],
            [command["name"] for command in commands],
        )
        add_command = commands[2]
        self.assertEqual("作品URLを追加してクロール対象に登録します。", add_command["description"])
        self.assertEqual(
            [
                {
                    "type": 3,
                    "name": "url",
                    "description": "追加したい作品URL",
                    "required": True,
                }
            ],
            add_command["options"],
        )
        self.assertEqual(
            "既存作品を起点に他媒体候補を探して supertwins を作成します。",
            commands[6]["description"],
        )
        self.assertNotIn("options", commands[6])
        self.assertEqual(
            "既存の supertwins を確認して誤登録を解除します。",
            commands[7]["description"],
        )
        self.assertNotIn("options", commands[7])

    def test_ensure_registered_from_env_uses_guild_registration_when_guild_id_is_present(self):
        from manga_watch.discord_command_registration import ensure_commands_registered_from_env

        session = FakeRequestsSession(
            put_responses=[FakeResponse(status_code=200, json_data=[{"id": "1"}])],
        )
        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "discord-token",
                "DISCORD_APPLICATION_ID": "app-123",
                "DISCORD_GUILD_ID": "guild-456",
            },
            clear=True,
        ):
            ensure_commands_registered_from_env(session=session)

        self.assertEqual(1, len(session.put_calls))
        self.assertIn("/applications/app-123/guilds/guild-456/commands", session.put_calls[0]["url"])

    def test_ensure_registered_from_env_resolves_application_id_via_oauth_me(self):
        from manga_watch.discord_command_registration import ensure_commands_registered_from_env

        session = FakeRequestsSession(
            get_responses=[FakeResponse(status_code=200, json_data={"id": "resolved-app"})],
            put_responses=[FakeResponse(status_code=200, json_data=[{"id": "1"}])],
        )
        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "discord-token",
            },
            clear=True,
        ):
            ensure_commands_registered_from_env(session=session)

        self.assertEqual(1, len(session.get_calls))
        self.assertIn("/oauth2/applications/@me", session.get_calls[0]["url"])
        self.assertIn("/applications/resolved-app/commands", session.put_calls[0]["url"])

    def test_ensure_registered_from_env_uses_custom_api_base_for_application_lookup(self):
        from manga_watch.discord_command_registration import ensure_commands_registered_from_env

        session = FakeRequestsSession(
            get_responses=[FakeResponse(status_code=200, json_data={"id": "resolved-app"})],
            put_responses=[FakeResponse(status_code=200, json_data=[{"id": "1"}])],
        )
        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "discord-token",
                "DISCORD_API_BASE_URL": "https://discord.example.test/api/v10",
            },
            clear=True,
        ):
            ensure_commands_registered_from_env(session=session)

        self.assertEqual(
            "https://discord.example.test/api/v10/oauth2/applications/@me",
            session.get_calls[0]["url"],
        )


if __name__ == "__main__":
    unittest.main()
