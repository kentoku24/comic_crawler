import importlib.util
import unittest
from pathlib import Path


def load_script_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "register_discord_commands.py"
    if not script_path.exists():
        raise AssertionError(f"missing helper script: {script_path}")

    spec = importlib.util.spec_from_file_location("register_discord_commands", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load import spec for: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RegisterDiscordCommandsTests(unittest.TestCase):
    def test_default_commands_include_add_with_required_url_option(self):
        module = load_script_module()

        add_command = next(
            command for command in module.DEFAULT_INTERACTION_COMMANDS if command["name"] == "add"
        )

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


if __name__ == "__main__":
    unittest.main()
