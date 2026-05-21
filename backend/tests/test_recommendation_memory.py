import unittest

from app.services.recommendation_memory import resolve_product_reference_from_history


class RecommendationMemoryTests(unittest.TestCase):
    def setUp(self):
        self.turns = [
            {
                "id": 1,
                "turn_index": 1,
                "request_text": "给我推荐三款床",
                "category_profile": {"categories": ["bed"]},
                "product_ids": [101, 102, 103],
                "items": [
                    {"slot": 1, "product_id": 101, "name": "Bed A"},
                    {"slot": 2, "product_id": 102, "name": "Bed B"},
                    {"slot": 3, "product_id": 103, "name": "Bed C"},
                ],
            },
            {
                "id": 2,
                "turn_index": 2,
                "request_text": "给我推荐三款桌子",
                "category_profile": {"categories": ["dining_table"]},
                "product_ids": [201, 202, 203],
                "items": [
                    {"slot": 1, "product_id": 201, "name": "Table A"},
                    {"slot": 2, "product_id": 202, "name": "Table B"},
                    {"slot": 3, "product_id": 203, "name": "Table C"},
                ],
            },
        ]

    def test_bare_ordinal_uses_latest_recommendation_turn(self):
        result = resolve_product_reference_from_history("我想知道第二款产品的信息", self.turns)

        self.assertEqual(result["target_product_id"], 202)
        self.assertEqual(result["turn_index"], 2)
        self.assertEqual(result["turn_product_ids"], [201, 202, 203])
        self.assertEqual(result["slot"], 2)
        self.assertFalse(result["needs_clarification"])

    def test_category_qualified_ordinal_uses_matching_prior_turn(self):
        result = resolve_product_reference_from_history("我想看看第二个床的效果图", self.turns)

        self.assertEqual(result["target_product_id"], 102)
        self.assertEqual(result["turn_index"], 1)
        self.assertEqual(result["slot"], 2)
        self.assertFalse(result["needs_clarification"])

    def test_multilingual_category_qualified_ordinal_is_language_independent(self):
        examples = [
            "Show me the second bed in a bedroom scene",
            "2番目のベッドの詳細を見たい",
            "두 번째 침대 정보를 보여줘",
            "Muéstrame la segunda cama",
            "Montrez-moi le deuxième lit",
        ]

        for message in examples:
            with self.subTest(message=message):
                result = resolve_product_reference_from_history(message, self.turns)
                self.assertEqual(result["target_product_id"], 102)
                self.assertEqual(result["turn_index"], 1)
                self.assertEqual(result["slot"], 2)

    def test_same_category_uses_latest_matching_turn(self):
        turns = [
            *self.turns,
            {
                "id": 3,
                "turn_index": 3,
                "request_text": "再推荐三款床",
                "category_profile": {"categories": ["bed"]},
                "product_ids": [301, 302, 303],
                "items": [
                    {"slot": 1, "product_id": 301, "name": "New Bed A"},
                    {"slot": 2, "product_id": 302, "name": "New Bed B"},
                    {"slot": 3, "product_id": 303, "name": "New Bed C"},
                ],
            },
        ]

        result = resolve_product_reference_from_history("第二个床的信息", turns)

        self.assertEqual(result["target_product_id"], 302)
        self.assertEqual(result["turn_index"], 3)
        self.assertEqual(result["slot"], 2)

    def test_turn_request_category_beats_product_title_fallback(self):
        turns = [
            {
                "id": 1,
                "turn_index": 1,
                "request_text": "给我推荐三款书桌",
                "category_profile": {"categories": ["desk"]},
                "product_ids": [101, 102, 103],
                "items": [
                    {"slot": 1, "product_id": 101, "name": "Desk A"},
                    {"slot": 2, "product_id": 102, "name": "Desk B"},
                    {"slot": 3, "product_id": 103, "name": "Desk C"},
                ],
            },
            {
                "id": 2,
                "turn_index": 2,
                "request_text": "我想买个桌子",
                "category_profile": {},
                "product_ids": [201, 202, 203],
                "items": [
                    {"slot": 1, "product_id": 201, "name": "餐桌 A"},
                    {"slot": 2, "product_id": 202, "name": "餐桌 B"},
                    {"slot": 3, "product_id": 203, "name": "可作为书桌的餐桌 C"},
                ],
            },
        ]

        result = resolve_product_reference_from_history("第二个书桌的信息", turns)

        self.assertEqual(result["target_product_id"], 102)
        self.assertEqual(result["turn_index"], 1)
        self.assertEqual(result["slot"], 2)

    def test_unresolved_category_reference_requests_clarification(self):
        result = resolve_product_reference_from_history("第二个沙发的信息", self.turns)

        self.assertIsNone(result["target_product_id"])
        self.assertTrue(result["needs_clarification"])


if __name__ == "__main__":
    unittest.main()
