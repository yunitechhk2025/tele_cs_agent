import unittest

from app.services.product_reference_parser import (
    is_active_product_reference_text,
    is_product_selection_only_text,
    parse_product_reference,
)


class ProductReferenceParserTests(unittest.TestCase):
    def assert_slot(self, text, slot, *, item_count=None, current_slot=None):
        result = parse_product_reference(text, item_count=item_count, current_slot=current_slot)
        self.assertEqual(result.slot, slot, msg=f"{text!r} resolved to {result}")

    def test_absolute_slot_expressions_across_supported_languages(self):
        examples = [
            ("第三个", 3),
            ("第3款", 3),
            ("No. 3", 3),
            ("number 3", 3),
            ("número 3", 3),
            ("numéro 3", 3),
            ("3番目", 3),
            ("3つ目", 3),
            ("3번 상품", 3),
            ("tercer sofá", 3),
            ("troisième canapé", 3),
            ("세 번째 제품", 3),
        ]

        for text, slot in examples:
            with self.subTest(text=text):
                self.assert_slot(text, slot, item_count=3)

    def test_from_end_and_middle_expressions_resolve_with_item_count(self):
        last_examples = [
            "倒数第一个",
            "倒數第一個",
            "last one",
            "último sofá",
            "dernier canapé",
            "最後の商品",
            "마지막 제품",
        ]
        second_from_end_examples = [
            "倒数第二个",
            "second-to-last",
            "penultimate",
            "penúltimo sofá",
            "avant-dernier canapé",
            "後ろから2番目",
            "뒤에서 두 번째",
        ]
        middle_examples = [
            "中间那个",
            "中間那款",
            "middle one",
            "el del medio",
            "celui du milieu",
            "真ん中の商品",
            "가운데 제품",
        ]

        for text in last_examples:
            with self.subTest(text=text):
                self.assert_slot(text, 3, item_count=3)
        for text in second_from_end_examples:
            with self.subTest(text=text):
                self.assert_slot(text, 2, item_count=3)
        for text in middle_examples:
            with self.subTest(text=text):
                self.assert_slot(text, 2, item_count=3)

        even_middle = parse_product_reference("middle one", item_count=4)
        self.assertIsNone(even_middle.slot)
        self.assertEqual(even_middle.relative_kind, "middle")

    def test_adjacent_and_two_choice_references_need_context(self):
        self.assert_slot("previous one", 1, item_count=3, current_slot=2)
        self.assert_slot("siguiente", 3, item_count=3, current_slot=2)
        self.assert_slot("前者", 1, item_count=2)
        self.assert_slot("后者", 2, item_count=2)
        self.assert_slot("former", 1, item_count=2)
        self.assert_slot("latter", 2, item_count=2)

        self.assertIsNone(parse_product_reference("previous one", item_count=3).slot)
        self.assertIsNone(parse_product_reference("former", item_count=3).slot)

    def test_active_product_reference_and_selection_only_detection(self):
        for text in ["这个", "this one", "este producto", "ce produit", "この商品", "이 제품"]:
            with self.subTest(text=text):
                self.assertTrue(is_active_product_reference_text(text))

        for text in ["#3", "tercer sofá", "last one", "el del medio", "倒数第一个"]:
            with self.subTest(text=text):
                self.assertTrue(is_product_selection_only_text(text))

        self.assertFalse(is_product_selection_only_text("show me the third sofa in a living room"))

    def test_does_not_misread_codes_quantities_sizes_or_years_as_slots(self):
        examples = [
            "JSQ0014A",
            "recommend 3 sofas",
            "quiero 3 sofás",
            "3-meter sofa",
            "2026 catalog",
            "last one",
        ]

        for text in examples:
            with self.subTest(text=text):
                result = parse_product_reference(text)
                self.assertIsNone(result.slot)


if __name__ == "__main__":
    unittest.main()
