import unittest

from app.services.product_i18n import (
    PRODUCT_TRANSLATABLE_FIELDS,
    build_translation_request_items,
    localize_product_payload,
    product_entry_to_payload,
    product_search_text,
    translation_map_from_entries,
)


class ProductI18nTests(unittest.TestCase):
    def test_localize_product_payload_prefers_turn_language(self):
        product = {
            "id": 10,
            "name": "中式沙发",
            "series": "山水系列",
            "space": "客厅",
            "style": "新中式",
            "color": "胡桃色",
            "material": "实木",
            "size": "2200mm",
            "description": "适合客厅的实木沙发。",
            "translations": {
                "en": {
                    "name": "Chinese-style sofa",
                    "series": "Shanshui Series",
                    "space": "living room",
                    "style": "modern Chinese",
                    "color": "walnut",
                    "material": "solid wood",
                    "size": "2200 mm",
                    "description": "A solid wood sofa for living rooms.",
                }
            },
        }

        out = localize_product_payload(product, "en")

        self.assertEqual(out["name"], "Chinese-style sofa")
        self.assertEqual(out["series"], "Shanshui Series")
        self.assertEqual(out["material"], "solid wood")
        self.assertEqual(out["source_language"], "en")
        self.assertEqual(out["translations"], product["translations"])

    def test_localize_product_payload_falls_back_to_english_then_source(self):
        product = {
            "name": "中式沙发",
            "series": "山水系列",
            "material": "实木",
            "translations": {
                "en": {"name": "Chinese-style sofa", "material": "solid wood"},
                "fr": {"name": "Canapé chinois"},
            },
        }

        out = localize_product_payload(product, "fr")

        self.assertEqual(out["name"], "Canapé chinois")
        self.assertEqual(out["material"], "solid wood")
        self.assertEqual(out["series"], "山水系列")

    def test_localize_product_payload_converts_source_fallback_for_traditional_chinese(self):
        product = {
            "name": "中式沙发",
            "material": "实木",
            "description": "为客厅推荐的产品。",
            "translations": {},
        }

        out = localize_product_payload(product, "zh-Hant")

        self.assertEqual(out["name"], "中式沙發")
        self.assertEqual(out["material"], "實木")
        self.assertEqual(out["description"], "為客廳推薦的產品。")

    def test_product_search_text_contains_source_and_translations(self):
        product = {
            "brand": "联邦家私",
            "name": "中式沙发",
            "series": "山水系列",
            "material": "实木",
            "translations": {
                "en": {"name": "Chinese-style sofa", "material": "solid wood"},
                "es": {"name": "sofá de estilo chino", "material": "madera maciza"},
            },
        }

        text = product_search_text(product)

        self.assertIn("中式沙发", text)
        self.assertIn("Chinese-style sofa", text)
        self.assertIn("sofá de estilo chino", text)
        self.assertIn("solid wood", text)
        self.assertIn("madera maciza", text)

    def test_translation_map_from_entries_serializes_supported_languages(self):
        class Entry:
            language = "zh-TW"
            product_name = "中式沙發"
            series_name = "山水系列"
            space = "客廳"
            style = "新中式"
            color = "胡桃色"
            material = "實木"
            size = "2200mm"
            description_text = "適合客廳的實木沙發。"
            detail_content_text = "細節內容"

        result = translation_map_from_entries([Entry()])

        self.assertEqual(result["zh-Hant"]["name"], "中式沙發")
        self.assertEqual(result["zh-Hant"]["material"], "實木")

    def test_product_entry_to_payload_includes_translations_and_images(self):
        class Translation:
            language = "en"
            product_name = "Chinese-style sofa"
            series_name = "Shanshui Series"
            space = "living room"
            style = "modern Chinese"
            color = "walnut"
            material = "solid wood"
            size = "2200 mm"
            description_text = "A solid wood sofa for living rooms."
            detail_content_text = ""

        class Image:
            local_path = "uploads/products/landbond/10/display_01.jpg"

        class Product:
            id = 10
            brand = "联邦家私"
            product_name = "中式沙发"
            series_name = "山水系列"
            space = "客厅"
            style = "新中式"
            color = "胡桃色"
            material = "实木"
            size = "2200mm"
            description_text = "适合客厅的实木沙发。"
            detail_content_text = ""
            buy_url = "https://example.com/buy"
            detail_url = "https://example.com/detail"
            images = [Image()]
            translations = [Translation()]

        payload = product_entry_to_payload(Product())

        self.assertEqual(payload["name"], "中式沙发")
        self.assertEqual(payload["translations"]["en"]["name"], "Chinese-style sofa")
        self.assertEqual(payload["image_paths"], ["uploads/products/landbond/10/display_01.jpg"])

    def test_build_translation_request_items_skips_existing_complete_language(self):
        product = {
            "id": 10,
            "brand": "联邦家私",
            "name": "中式沙发",
            "series": "山水系列",
            "translations": {
                "en": {field: f"filled-{field}" for field in PRODUCT_TRANSLATABLE_FIELDS}
            },
        }

        items = build_translation_request_items(
            [product],
            target_languages=["en", "fr"],
            only_missing=True,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["product_id"], 10)
        self.assertEqual(items[0]["language"], "fr")

    def test_build_translation_request_items_ignores_empty_source_fields_for_completeness(self):
        product = {
            "id": 10,
            "name": "中式沙发",
            "series": "",
            "space": "",
            "material": "实木",
            "translations": {
                "en": {"name": "Chinese-style sofa", "material": "solid wood"}
            },
        }

        items = build_translation_request_items(
            [product],
            target_languages=["en"],
            only_missing=True,
        )

        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
