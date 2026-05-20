import json
import unittest

from scripts.fill_product_translations import (
    build_translation_messages,
    format_progress_bar,
    parse_translation_response,
    traditional_rows_from_products,
)


class FillProductTranslationsTests(unittest.TestCase):
    def test_build_translation_messages_requests_strict_json(self):
        items = [
            {
                "product_id": 10,
                "language": "en",
                "brand": "联邦家私",
                "fields": {"name": "中式沙发", "material": "实木"},
            }
        ]

        messages = build_translation_messages(items)

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("strict JSON", messages[0]["content"])
        self.assertIn('"product_id": 10', messages[1]["content"])
        self.assertIn('"language": "en"', messages[1]["content"])

    def test_parse_translation_response_accepts_array_or_object_wrapper(self):
        raw = json.dumps({
            "translations": [
                {
                    "product_id": 10,
                    "language": "fr",
                    "fields": {"name": "Canapé chinois", "material": "bois massif"},
                }
            ]
        })

        parsed = parse_translation_response(raw)

        self.assertEqual(parsed[(10, "fr")]["name"], "Canapé chinois")
        self.assertEqual(parsed[(10, "fr")]["material"], "bois massif")

    def test_traditional_rows_from_products_uses_local_conversion(self):
        rows = traditional_rows_from_products([
            {
                "id": 10,
                "name": "中式沙发",
                "material": "实木",
                "description": "为客厅推荐的产品。",
                "translations": {},
            }
        ])

        self.assertEqual(rows[(10, "zh-Hant")]["name"], "中式沙發")
        self.assertEqual(rows[(10, "zh-Hant")]["material"], "實木")
        self.assertEqual(rows[(10, "zh-Hant")]["description"], "為客廳推薦的產品。")

    def test_traditional_rows_from_products_skips_when_non_empty_source_fields_are_done(self):
        rows = traditional_rows_from_products([
            {
                "id": 10,
                "name": "中式沙发",
                "series": "",
                "material": "实木",
                "translations": {
                    "zh-Hant": {"name": "中式沙發", "material": "實木"}
                },
            }
        ])

        self.assertEqual(rows, {})

    def test_format_progress_bar_shows_counts_and_percentage(self):
        line = format_progress_bar(15, 30, width=10)

        self.assertEqual(line, "[#####-----] 15/30 50.0%")

    def test_format_progress_bar_handles_empty_work(self):
        line = format_progress_bar(0, 0, width=10)

        self.assertEqual(line, "[##########] 0/0 100.0%")


if __name__ == "__main__":
    unittest.main()
