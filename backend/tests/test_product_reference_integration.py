import unittest

from app.services.llm_service import classify_customer_intent_fast
from app.telegram_bot import (
    is_product_selection_only,
    is_recent_product_followup,
    resolve_recommended_product_reference_locally,
)


class ProductReferenceIntegrationTests(unittest.TestCase):
    def test_telegram_local_resolution_uses_shared_relative_references(self):
        product_ids = [101, 102, 103]

        self.assertEqual(resolve_recommended_product_reference_locally("倒数第一个", product_ids), 103)
        self.assertEqual(resolve_recommended_product_reference_locally("last one", product_ids), 103)
        self.assertEqual(resolve_recommended_product_reference_locally("penúltimo sofá", product_ids), 102)
        self.assertEqual(resolve_recommended_product_reference_locally("el del medio", product_ids), 102)

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


if __name__ == "__main__":
    unittest.main()
