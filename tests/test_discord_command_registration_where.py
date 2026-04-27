import unittest

from manga_watch.discord_where import WHERE_COMMAND


class DiscordWhereCommandRegistrationTests(unittest.TestCase):
    def test_default_command_definitions_include_where(self):
        from manga_watch.discord_command_registration import default_interaction_commands

        commands = default_interaction_commands()
        where_command = next(command for command in commands if command["name"] == WHERE_COMMAND)

        self.assertEqual("指定話を読める媒体を横断検索します。", where_command["description"])
        self.assertEqual(
            [
                {
                    "type": 3,
                    "name": "query",
                    "description": "探したい作品名",
                    "required": True,
                },
                {
                    "type": 3,
                    "name": "episode",
                    "description": "探したい話数。例: 第1話",
                    "required": True,
                },
            ],
            where_command["options"],
        )


if __name__ == "__main__":
    unittest.main()
