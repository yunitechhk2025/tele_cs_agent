import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.services.scene_service import (
    _normalize_dashscope_image_reference,
    _product_image_reference_value,
)


class SceneReferenceFormatTests(unittest.TestCase):
    def test_dashscope_reference_keeps_valid_data_url(self):
        data_url = "data:image/png;base64,QUJDRA=="
        self.assertEqual(
            _normalize_dashscope_image_reference(data_url),
            data_url,
        )

    def test_dashscope_reference_keeps_http_url(self):
        url = "https://example.com/product.jpg"
        self.assertEqual(_normalize_dashscope_image_reference(url), url)

    def test_dashscope_reference_rejects_invalid_data_url(self):
        self.assertEqual(
            _normalize_dashscope_image_reference("data:image/png;base64,not valid base64"),
            "",
        )

    def test_dashscope_reference_rejects_localhost_url(self):
        self.assertEqual(
            _normalize_dashscope_image_reference("http://localhost:8000/api/products/1/images/0"),
            "",
        )

    def test_product_image_reference_uses_complete_data_url_for_local_image(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "product.png"
            path.write_bytes(b"ABCD")
            image = SimpleNamespace(source_url="", local_path=str(path))
            self.assertEqual(
                _product_image_reference_value(image),
                "data:image/png;base64,QUJDRA==",
            )


if __name__ == "__main__":
    unittest.main()
