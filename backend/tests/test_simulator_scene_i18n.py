import ast
import unittest
from pathlib import Path


ROUTER_PATH = Path(__file__).resolve().parents[1] / "app" / "api" / "router.py"


def _function_source(name: str) -> str:
    source = ROUTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{name} not found in router.py")


class SimulatorSceneI18nTests(unittest.TestCase):
    def test_scene_events_use_record_turn_language_not_current_conversation_language(self):
        source = _function_source("_build_simulator_scene_events")

        self.assertIn("_resolve_scene_record_language", source)
        self.assertNotIn("SCENE_RESULT_MESSAGES.get(ui_lang, SCENE_RESULT_MESSAGES[\"en\"])", source)
        self.assertNotIn("SCENE_RESULT_LINK_LABELS.get(ui_lang, SCENE_RESULT_LINK_LABELS[\"en\"])", source)
        self.assertIn("get_localized_static_text(SCENE_RESULT_MESSAGES", source)
        self.assertIn("get_localized_static_dict(SCENE_RESULT_LINK_LABELS", source)

    def test_scene_record_language_resolver_uses_matching_user_message_language(self):
        source = _function_source("_resolve_scene_record_language")

        self.assertIn("Message.role == MessageRole.USER", source)
        self.assertIn("Message.content == record.request_text", source)
        self.assertIn("Message.language", source)
        self.assertIn("conversation_language", source)


if __name__ == "__main__":
    unittest.main()
