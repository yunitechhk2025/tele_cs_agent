import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models import MessageRole
from app.services.customer_service_service import (
    _send_product_recommendation_payload,
    _send_scene_result_payload,
)


class CustomerServiceDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_payloads_remain_pending_without_telegram_bot(self):
        send_payloads = (
            _send_product_recommendation_payload,
            _send_scene_result_payload,
        )

        for send_payload in send_payloads:
            with self.subTest(send_payload=send_payload.__name__):
                db = SimpleNamespace(commit=AsyncMock())
                conversation = SimpleNamespace(id=1, telegram_chat_id="12345")
                draft = SimpleNamespace(
                    status="sending",
                    error_message="",
                    language="zh-Hans",
                    draft_text="待发送内容",
                )

                with patch(
                    "app.services.customer_service_service._resolve_bot_for_conversation",
                    new=AsyncMock(return_value=None),
                ):
                    sent_text = await send_payload(
                        db,
                        conversation,
                        draft,
                        {},
                        MessageRole.ASSISTANT,
                    )

                self.assertIsNone(sent_text)
                self.assertEqual(draft.status, "pending")
                self.assertEqual(draft.error_message, "Telegram bot not available")
                db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
