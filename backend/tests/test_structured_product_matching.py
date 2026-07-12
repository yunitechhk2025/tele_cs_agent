import asyncio
import unittest
from unittest.mock import patch

from app.services.llm_service import ai_select_products, build_product_constraint_notice
from app.services.product_taxonomy import infer_primary_category


class StructuredProductMatchingTests(unittest.TestCase):
    def test_ai_select_products_uses_structured_category_before_text_noise(self):
        products = [
            {
                "id": 1,
                "name": "联邦书桌 A",
                "primary_category": "desk",
                "normalized_space": "study",
                "image_paths": ["a.jpg"],
                "buy_url": "http://example.com/a",
            },
            {
                "id": 2,
                "name": "联邦沙发背柜",
                "primary_category": "cabinet",
                "description": "适合放在沙发背后，也可以放书。",
                "image_paths": ["b.jpg"],
                "buy_url": "http://example.com/b",
            },
            {
                "id": 3,
                "name": "办公椅",
                "primary_category": "chair",
                "description": "可搭配书桌使用。",
                "image_paths": ["c.jpg"],
                "buy_url": "http://example.com/c",
            },
        ]
        profile = {
            "categories": ["desk"],
            "colors": [],
            "styles": [],
            "materials": [],
            "spaces": ["study"],
            "brands": [],
            "hard_constraints": ["categories"],
            "confidence": 0.93,
        }

        selected = asyncio.run(
            ai_select_products("recommend me a desk", products, request_profile=profile)
        )

        self.assertEqual(selected[0], 1)
        self.assertNotIn(2, selected)
        self.assertNotIn(3, selected)

    def test_constraint_notice_uses_profile_to_report_unsatisfied_inventory(self):
        products = [
            {
                "id": 1,
                "name": "中式真皮沙发",
                "primary_category": "sofa",
                "normalized_style": "chinese",
                "normalized_color": "brown",
                "image_paths": ["a.jpg"],
            }
        ]
        profile = {
            "categories": ["sofa"],
            "colors": ["purple"],
            "styles": ["chinese"],
            "materials": [],
            "spaces": [],
            "brands": [],
            "hard_constraints": ["categories", "colors", "styles"],
            "confidence": 0.9,
        }

        notice = build_product_constraint_notice(
            "给我推荐一款紫色中式沙发",
            products,
            "zh-Hans",
            request_profile=profile,
        )

        self.assertTrue(notice["has_notice"])
        self.assertIn("紫色", notice["text"])
        self.assertEqual(notice["missing"][0]["dimension"], "colors")

    def test_taxonomy_does_not_match_latin_category_terms_inside_other_words(self):
        category, _confidence, _reason = infer_primary_category(
            {
                "name": "破晓",
                "series": "优眠系列",
                "space": "卧室",
                "description": "密集型排骨架有效承托床垫。",
                "translations": {
                    "fr": {
                        "name": "Aube",
                        "series": "Série Sommeil Premium",
                        "space": "Chambre à coucher",
                        "description": "Le sommier à lattes soutient efficacement le matelas.",
                    }
                },
            }
        )

        self.assertNotEqual(category, "sofa")

    def test_ai_select_products_reorders_llm_result_by_satisfiable_constraints(self):
        products = [
            {
                "id": 1,
                "name": "破晓",
                "series": "优眠系列",
                "space": "卧室",
                "primary_category": "",
                "normalized_space": "bedroom",
                "translations": {
                    "fr": {
                        "name": "Aube",
                        "space": "Chambre à coucher",
                    }
                },
                "image_paths": ["bed.jpg"],
            },
            {
                "id": 2,
                "name": "现代天空之城沙发",
                "primary_category": "sofa",
                "material": "松木框架/金属脚（哑黑色）",
                "normalized_space": "living_room",
                "image_paths": ["gray.jpg"],
            },
            {
                "id": 3,
                "name": "黑色真皮沙发",
                "primary_category": "sofa",
                "normalized_color": "black",
                "normalized_space": "living_room",
                "image_paths": ["black.jpg"],
            },
        ]
        profile = {
            "categories": ["sofa"],
            "colors": ["black"],
            "styles": [],
            "materials": [],
            "spaces": [],
            "brands": [],
            "hard_constraints": ["categories", "colors"],
            "confidence": 0.9,
        }

        async def fake_chat_completion(*_args, **_kwargs):
            return "[1, 2, 3]"

        with patch("app.services.llm_service._chat_completion", side_effect=fake_chat_completion):
            selected = asyncio.run(
                ai_select_products("推荐一款黑色沙发", products, request_profile=profile)
            )

        self.assertEqual(selected[0], 3)
        self.assertNotIn(1, selected)

    def test_ai_select_products_excludes_seen_ids_for_batch_refresh(self):
        products = [
            {
                "id": 1,
                "name": "联邦书桌 A",
                "primary_category": "desk",
                "normalized_space": "study",
                "image_paths": ["desk-a.jpg"],
            },
            {
                "id": 2,
                "name": "联邦书桌 B",
                "primary_category": "desk",
                "normalized_space": "study",
                "image_paths": ["desk-b.jpg"],
            },
            {
                "id": 3,
                "name": "联邦书桌 C",
                "primary_category": "desk",
                "normalized_space": "study",
                "image_paths": ["desk-c.jpg"],
            },
            {
                "id": 4,
                "name": "联邦沙发 A",
                "primary_category": "sofa",
                "normalized_space": "living_room",
                "image_paths": ["sofa-a.jpg"],
            },
        ]
        profile = {
            "categories": ["desk"],
            "spaces": ["study"],
            "colors": [],
            "styles": [],
            "materials": [],
            "brands": [],
            "hard_constraints": ["categories", "spaces"],
            "confidence": 0.9,
        }

        selected = asyncio.run(
            ai_select_products(
                "换一批",
                products,
                request_profile=profile,
                exclude_product_ids=[1, 2],
                require_full_match=True,
            )
        )

        self.assertEqual(selected, [3])

    def test_ai_select_products_returns_empty_when_no_more_full_matches(self):
        products = [
            {
                "id": 1,
                "name": "联邦书桌 A",
                "primary_category": "desk",
                "normalized_space": "study",
                "image_paths": ["desk-a.jpg"],
            },
            {
                "id": 2,
                "name": "联邦书桌 B",
                "primary_category": "desk",
                "normalized_space": "study",
                "image_paths": ["desk-b.jpg"],
            },
            {
                "id": 3,
                "name": "联邦沙发 A",
                "primary_category": "sofa",
                "normalized_space": "living_room",
                "image_paths": ["sofa-a.jpg"],
            },
        ]
        profile = {
            "categories": ["desk"],
            "spaces": ["study"],
            "colors": [],
            "styles": [],
            "materials": [],
            "brands": [],
            "hard_constraints": ["categories", "spaces"],
            "confidence": 0.9,
        }

        selected = asyncio.run(
            ai_select_products(
                "换一批",
                products,
                request_profile=profile,
                exclude_product_ids=[1, 2],
                require_full_match=True,
            )
        )

        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
