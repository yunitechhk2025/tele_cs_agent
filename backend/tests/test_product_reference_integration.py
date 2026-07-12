import asyncio
import unittest
from unittest.mock import patch

from app.services.llm_service import classify_customer_intent, classify_customer_intent_fast
from app.telegram_bot import (
    build_recommendation_refresh_profile,
    collect_recommendation_refresh_excluded_ids,
    is_product_selection_only,
    is_recent_product_followup,
    resolve_recommended_product_reference_locally,
    should_use_recommendation_refresh,
)


class ProductReferenceIntegrationTests(unittest.TestCase):
    def test_telegram_local_resolution_uses_shared_relative_references(self):
        product_ids = [101, 102, 103]

        self.assertEqual(
            resolve_recommended_product_reference_locally("倒数第一个", product_ids), 103
        )
        self.assertEqual(
            resolve_recommended_product_reference_locally("last one", product_ids), 103
        )
        self.assertEqual(
            resolve_recommended_product_reference_locally("penúltimo sofá", product_ids), 102
        )
        self.assertEqual(
            resolve_recommended_product_reference_locally("el del medio", product_ids), 102
        )

    def test_selection_and_followup_detection_cover_relative_references(self):
        for text in ["last one", "倒数第一个", "el del medio"]:
            with self.subTest(text=text):
                self.assertTrue(is_product_selection_only(text))
                self.assertTrue(is_recent_product_followup(text))

    def test_fast_intent_treats_relative_reference_as_scene_confirmation(self):
        for text in ["last one", "倒数第一个", "el del medio"]:
            with self.subTest(text=text):
                intent = classify_customer_intent_fast(text, has_pending_scene_confirmation=True)
                self.assertIsNotNone(intent)
                self.assertEqual(intent["primary_intent"], "scene_image_confirmation")

    def test_fast_intent_treats_batch_refresh_as_product_recommendation(self):
        examples = [
            "换一批",
            "再换一批",
            "还有别的吗",
            "有没有其他的沙发？",
            "有没有别的沙发",
            "有沒有其他的沙發？",
            "show me different options",
            "Muéstrame otras opciones",
            "Autres options s'il vous plaît",
        ]

        for text in examples:
            with self.subTest(text=text):
                intent = classify_customer_intent_fast(text)
                self.assertIsNotNone(intent)
                self.assertEqual(intent["primary_intent"], "product_recommendation")

    def test_recommendation_refresh_reuses_latest_turn_profile_and_excludes_history(self):
        current_profile = {
            "categories": [],
            "spaces": [],
            "colors": [],
            "styles": [],
            "materials": [],
            "brands": [],
            "hard_constraints": [],
            "confidence": 0.35,
        }
        turns = [
            {
                "turn_index": 1,
                "category_profile": {"categories": ["sofa"], "colors": ["black"]},
                "product_ids": [101, 102],
            },
            {
                "turn_index": 2,
                "category_profile": {"categories": ["desk"], "spaces": ["study"]},
                "product_ids": [201, 202],
            },
        ]

        profile = build_recommendation_refresh_profile(current_profile, turns)
        excluded_ids = collect_recommendation_refresh_excluded_ids(turns)

        self.assertEqual(profile["categories"], ["desk"])
        self.assertEqual(profile["spaces"], ["study"])
        self.assertEqual(profile["hard_constraints"], ["categories", "spaces"])
        self.assertEqual(excluded_ids, [101, 102, 201, 202])

    def test_router_prompt_and_result_support_refresh_slot(self):
        captured_messages = []

        async def fake_chat_completion(*, messages, **_kwargs):
            captured_messages.extend(messages)
            return (
                '{"primary_intent":"product_recommendation","secondary_intents":[],'
                '"confidence":0.78,'
                '"slots":{"target_product_id":null,"scene_name":"","style_hint":"",'
                '"file_ids":[],"is_recommendation_refresh":true},'
                '"needs_human":false,"clarification_question":"",'
                '"reason":"customer asks for other same-request options"}'
            )

        with (
            patch("app.services.llm_service._chat_completion", side_effect=fake_chat_completion),
            patch(
                "app.services.llm_service.get_llm_settings",
                return_value={"profile_llm_timeout_seconds": "4"},
            ),
        ):
            intent = asyncio.run(
                classify_customer_intent(
                    "这些都不合适，能不能继续看同类款",
                    products=[{"id": 1, "name": "联邦书桌 A"}],
                    recent_product_ids=[1],
                    chat_history=[],
                )
            )

        self.assertTrue(intent["slots"]["is_recommendation_refresh"])
        self.assertIn("is_recommendation_refresh", captured_messages[0]["content"])

    def test_router_timeout_falls_back_without_hanging(self):
        async def slow_chat_completion(*, messages, **_kwargs):
            await asyncio.sleep(0.05)
            return (
                '{"primary_intent":"product_recommendation","secondary_intents":[],'
                '"confidence":0.78,"slots":{"is_recommendation_refresh":true},'
                '"needs_human":false,"clarification_question":"","reason":"slow"}'
            )

        with patch("app.services.llm_service._chat_completion", side_effect=slow_chat_completion):
            intent = asyncio.run(
                classify_customer_intent(
                    "这些都不合适，能不能继续看同类款",
                    products=[{"id": 1, "name": "联邦书桌 A"}],
                    recent_product_ids=[1],
                    chat_history=[],
                    timeout_seconds=0.01,
                )
            )

        self.assertEqual(intent["primary_intent"], "general_question")
        self.assertEqual(intent["confidence"], 0.0)
        self.assertEqual(intent["reason"], "intent classifier timed out")

    def test_refresh_semantics_require_recommendation_history(self):
        self.assertFalse(should_use_recommendation_refresh("换一批", {}, []))
        self.assertTrue(
            should_use_recommendation_refresh(
                "这些都不合适，能不能继续看同类款",
                {"is_recommendation_refresh": True},
                [
                    {
                        "turn_index": 1,
                        "product_ids": [101],
                        "category_profile": {"categories": ["desk"]},
                    }
                ],
            )
        )


if __name__ == "__main__":
    unittest.main()
