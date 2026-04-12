import unittest

from manga_watch.discord_fetch import FETCH_COMMAND
from manga_watch.discord_latest import LATEST_COMMAND
from manga_watch.discord_remove import REMOVE_COMMAND
from manga_watch.discord_search import SEARCH_COMMAND


class DiscordSearchCommandRegistrationTests(unittest.TestCase):
    def test_default_command_definitions_include_search(self):
        from manga_watch.discord_command_registration import default_interaction_commands

        commands = default_interaction_commands()

        self.assertEqual(
            [
                LATEST_COMMAND,
                FETCH_COMMAND,
                "add",
                SEARCH_COMMAND,
                REMOVE_COMMAND,
                "supertwins-search",
                "supertwins-manage",
            ],
            [command["name"] for command in commands],
        )
        search_command = commands[3]
        self.assertEqual("媒体ごとに作品名で検索します。", search_command["description"])
        self.assertEqual(
            [
                {
                    "type": 3,
                    "name": "source",
                    "description": "検索したい媒体",
                    "required": True,
                    "choices": [
                        {"name": "champion-cross", "value": "champion-cross"},
                        {"name": "kakuyomu", "value": "kakuyomu"},
                        {"name": "comic-walker", "value": "comic-walker"},
                    ],
                },
                {
                    "type": 3,
                    "name": "query",
                    "description": "検索したい文字列",
                    "required": True,
                },
                {
                    "type": 3,
                    "name": "visibility",
                    "description": "watchlist に追加するときの表示状態",
                    "required": False,
                    "choices": [
                        {"name": "visible", "value": "visible"},
                        {"name": "hidden", "value": "hidden"},
                    ],
                },
            ],
            search_command["options"],
        )


if __name__ == "__main__":
    unittest.main()
