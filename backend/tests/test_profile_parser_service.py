import unittest

from app.services.profile_parser_service import (
    build_fallback_product_request_profile,
    normalize_product_request_profile,
    normalize_scene_request_profile,
)


class ProfileParserServiceTests(unittest.TestCase):
    def test_normalizes_llm_product_profile_to_canonical_values(self):
        profile = normalize_product_request_profile(
            {
                "language": "zh-Hant",
                "categories": ["書桌", "desk", "unknown"],
                "colors": ["紫色"],
                "styles": ["中式"],
                "materials": ["实木"],
                "spaces": ["书房"],
                "brands": ["红苹果"],
                "hard_constraints": ["category", "colors", "nonsense"],
                "confidence": 1.8,
                "needs_human": False,
                "reason": "用户明确要求",
            },
            user_message="給我推薦一款紫色中式書桌",
            fallback_language="zh-Hant",
        )

        self.assertEqual(profile["language"], "zh-Hant")
        self.assertEqual(profile["categories"], ["desk"])
        self.assertEqual(profile["colors"], ["purple"])
        self.assertEqual(profile["styles"], ["chinese"])
        self.assertEqual(profile["materials"], ["solid_wood"])
        self.assertEqual(profile["spaces"], ["study"])
        self.assertEqual(profile["brands"], ["redapple"])
        self.assertEqual(profile["hard_constraints"], ["categories", "colors"])
        self.assertEqual(profile["confidence"], 1.0)
        self.assertFalse(profile["needs_human"])

    def test_fallback_profile_keeps_multilingual_category_consistent(self):
        examples = [
            "给我推荐一款书桌",
            "給我推薦一款書桌",
            "recommend me a desk",
            "おすすめの机を教えてください",
            "책상을 추천해 주세요",
            "recomiéndame un escritorio",
            "recommandez-moi un bureau",
        ]

        for message in examples:
            with self.subTest(message=message):
                profile = build_fallback_product_request_profile(message, "en")
                self.assertEqual(profile["categories"], ["desk"])

    def test_fallback_profile_supports_catalog_specific_categories(self):
        examples = {
            "给我推荐一款床垫": "mattress",
            "推荐一个梳妆台": "dressing_table",
            "show me bedding": "bedding",
            "推荐一个客厅圆几": "coffee_table",
        }

        for message, category in examples.items():
            with self.subTest(message=message):
                profile = build_fallback_product_request_profile(message, "zh-Hans")
                self.assertEqual(profile["categories"], [category])

    def test_fallback_profile_maps_generic_table_to_table_families(self):
        examples = [
            "推荐一款桌子",
            "recommend a table",
            "mesa recomendada",
            "テーブルをおすすめしてください",
            "테이블을 추천해 주세요",
        ]

        for message in examples:
            with self.subTest(message=message):
                profile = build_fallback_product_request_profile(message, "zh-Hans")
                self.assertEqual(profile["categories"], ["dining_table", "coffee_table", "desk"])
                self.assertFalse(profile["needs_human"])

    def test_low_confidence_llm_handoff_is_overridden_when_local_profile_can_recommend(self):
        profile = normalize_product_request_profile(
            {
                "language": "zh-Hans",
                "categories": [],
                "materials": [],
                "hard_constraints": [],
                "confidence": 0.1,
                "needs_human": True,
                "reason": "too vague",
            },
            user_message="推荐一款桌子",
            fallback_language="zh-Hans",
        )

        self.assertEqual(profile["categories"], ["dining_table", "coffee_table", "desk"])
        self.assertFalse(profile["needs_human"])
        self.assertEqual(profile["source"], "local_rules_after_profile_handoff")

    def test_scene_profile_preserves_requested_scene_style_and_slot(self):
        profile = normalize_scene_request_profile(
            {
                "language": "zh-Hans",
                "is_scene_request": True,
                "target_product_slot": 3,
                "target_product_id": None,
                "scene_name": "餐厅",
                "style_hint": "中式复古",
                "requirements": ["中式", "复古", "餐厅"],
                "confidence": 0.88,
                "needs_human": False,
            },
            user_message="我想看看第三款餐桌在中式复古风格餐厅的效果图",
            fallback_language="zh-Hans",
        )

        self.assertTrue(profile["is_scene_request"])
        self.assertEqual(profile["target_product_slot"], 3)
        self.assertIsNone(profile["target_product_id"])
        self.assertEqual(profile["scene_name"], "餐厅")
        self.assertEqual(profile["style_hint"], "中式复古")
        self.assertEqual(profile["confidence"], 0.88)


if __name__ == "__main__":
    unittest.main()
