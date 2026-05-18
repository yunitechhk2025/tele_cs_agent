import ast
import unittest
from pathlib import Path

from app.services.i18n import get_localized_static_text


TELEGRAM_BOT_PATH = Path(__file__).resolve().parents[1] / "app" / "telegram_bot.py"
SCENE_MESSAGE_MAPS = (
    "SCENE_FOLLOWUP_MESSAGES",
    "SCENE_GENERATING_MESSAGES",
    "SCENE_FAILED_MESSAGES",
    "SCENE_TIMEOUT_MESSAGES",
)


def _literal_dict(name: str) -> dict[str, str]:
    tree = ast.parse(TELEGRAM_BOT_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in telegram_bot.py")


class TelegramStaticI18nTests(unittest.TestCase):
    def test_scene_message_maps_have_supported_non_english_locales(self):
        for map_name in SCENE_MESSAGE_MAPS:
            messages = _literal_dict(map_name)
            with self.subTest(map_name=map_name):
                for lang in ("ja", "ko", "es", "fr"):
                    self.assertIn(lang, messages)
                    self.assertNotEqual(get_localized_static_text(messages, lang), messages["en"])

    def test_japanese_scene_followup_does_not_fallback_to_english(self):
        messages = _literal_dict("SCENE_FOLLOWUP_MESSAGES")

        rendered = get_localized_static_text(messages, "ja").format(scene="書斎")

        self.assertIn("書斎", rendered)
        self.assertIn("商品", rendered)
        self.assertNotIn("If you'd like", rendered)


if __name__ == "__main__":
    unittest.main()
