import unittest

from app.services.scene_service import _normalize_dashscope_image_reference


class SceneReferenceFormatTests(unittest.TestCase):
    def test_dashscope_reference_strips_data_url_prefix(self):
        self.assertEqual(
            _normalize_dashscope_image_reference("data:image/png;base64,QUJDRA=="),
            "QUJDRA==",
        )

    def test_dashscope_reference_keeps_http_url(self):
        url = "https://example.com/product.jpg"
        self.assertEqual(_normalize_dashscope_image_reference(url), url)


if __name__ == "__main__":
    unittest.main()
