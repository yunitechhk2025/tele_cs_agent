import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.scene_service import (
    _normalize_dashscope_image_reference,
    _public_product_image_url,
)


class SceneReferenceFormatTests(unittest.TestCase):
    def test_dashscope_reference_rejects_data_url(self):
        self.assertEqual(
            _normalize_dashscope_image_reference("data:image/png;base64,QUJDRA=="),
            "",
        )

    def test_dashscope_reference_keeps_http_url(self):
        url = "https://example.com/product.jpg"
        self.assertEqual(_normalize_dashscope_image_reference(url), url)

    def test_dashscope_reference_rejects_localhost_url(self):
        self.assertEqual(
            _normalize_dashscope_image_reference("http://localhost:8000/api/products/1/images/0"),
            "",
        )

    def test_public_product_image_url_uses_public_backend_url(self):
        image = SimpleNamespace(product_entry_id=12, display_order=3)
        with patch("app.services.scene_service.settings.BACKEND_URL", "https://cs.yuniagent.ai"):
            self.assertEqual(
                _public_product_image_url(image),
                "https://cs.yuniagent.ai/api/products/12/images/3",
            )


if __name__ == "__main__":
    unittest.main()
