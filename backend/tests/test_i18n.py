import unittest

from app.services.i18n import (
    detect_chinese_script,
    get_localized_static_dict,
    get_localized_static_text,
    normalize_language_code,
    resolve_reply_language,
    to_traditional_chinese,
)


class LanguageI18nTests(unittest.TestCase):
    def test_normalize_chinese_variants(self):
        self.assertEqual(normalize_language_code("zh-CN"), "zh-Hans")
        self.assertEqual(normalize_language_code("zh-Hans"), "zh-Hans")
        self.assertEqual(normalize_language_code("zh-SG"), "zh-Hans")
        self.assertEqual(normalize_language_code("zh-TW"), "zh-Hant")
        self.assertEqual(normalize_language_code("zh-HK"), "zh-Hant")
        self.assertEqual(normalize_language_code("zh-Hant"), "zh-Hant")
        self.assertEqual(normalize_language_code("zh"), "zh-Hans")

    def test_detect_chinese_script_prefers_traditional_only_characters(self):
        self.assertEqual(detect_chinese_script("請問這個櫃子的材質是什麼？"), "zh-Hant")
        self.assertEqual(detect_chinese_script("请问这个柜子的材质是什么？"), "zh-Hans")

    def test_normalize_other_supported_languages(self):
        self.assertEqual(normalize_language_code("EN-us"), "en")
        self.assertEqual(normalize_language_code("ja-JP"), "ja")
        self.assertEqual(normalize_language_code("ko-KR"), "ko")
        self.assertEqual(normalize_language_code("es-MX"), "es")
        self.assertEqual(normalize_language_code("fr-CA"), "fr")

    def test_resolve_reply_language_uses_current_supported_language(self):
        self.assertEqual(
            resolve_reply_language("zh-TW", previous_language="en", text="請問有沙發嗎？"),
            "zh-Hant",
        )

    def test_resolve_reply_language_falls_back_to_previous_for_unknown(self):
        self.assertEqual(resolve_reply_language("de", previous_language="fr"), "fr")
        self.assertEqual(resolve_reply_language("", previous_language="zh-Hant"), "zh-Hant")

    def test_resolve_reply_language_defaults_to_english_without_supported_signal(self):
        self.assertEqual(resolve_reply_language("de", previous_language="de"), "en")
        self.assertEqual(resolve_reply_language("", previous_language=""), "en")

    def test_to_traditional_chinese_converts_common_service_copy(self):
        self.assertEqual(
            to_traditional_chinese("为您推荐以下产品，请查看详情链接。"),
            "為您推薦以下產品，請查看詳情連結。",
        )

    def test_get_localized_static_text_supports_traditional_fallback(self):
        messages = {
            "zh": "为您推荐以下产品：",
            "en": "Here are some products:",
        }
        self.assertEqual(get_localized_static_text(messages, "zh-Hant"), "為您推薦以下產品：")

    def test_get_localized_static_dict_supports_traditional_fallback(self):
        labels = {
            "zh": {"series": "系列", "material": "材质", "view": "查看详情"},
            "en": {"series": "Series", "material": "Material", "view": "View details"},
        }
        self.assertEqual(
            get_localized_static_dict(labels, "zh-Hant"),
            {"series": "系列", "material": "材質", "view": "查看詳情"},
        )


if __name__ == "__main__":
    unittest.main()
