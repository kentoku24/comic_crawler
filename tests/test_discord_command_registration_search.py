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
                    "name": "query",
                    "description": "検索したい文字列",
                    "required": True,
                },
                {
                    "type": 3,
                    "name": "source",
                    "description": "検索したい媒体",
                    "required": False,
                    "choices": [
                        {"name": "comic-walker", "value": "comic-walker"},
                        {"name": "comic-action", "value": "comic-action"},
                        {"name": "comic-earthstar", "value": "comic-earthstar"},
                        {"name": "comicborder", "value": "comicborder"},
                        {"name": "comic-trail", "value": "comic-trail"},
                        {"name": "kuragebunch", "value": "kuragebunch"},
                        {"name": "shonenjumpplus", "value": "shonenjumpplus"},
                        {"name": "sunday-webry", "value": "sunday-webry"},
                        {"name": "champion-cross", "value": "champion-cross"},
                        {"name": "magapoke", "value": "magapoke"},
                        {"name": "firecross", "value": "firecross"},
                        {"name": "takecomic", "value": "takecomic"},
                        {"name": "nicovideo-manga", "value": "nicovideo-manga"},
                        {"name": "kakuyomu", "value": "kakuyomu"},
                        {"name": "gaugau", "value": "gaugau"},
                    ],
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
