import logging
import json
from datetime import datetime

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import ConversationProcessingState, ConversationTurnMetric

logger = logging.getLogger(__name__)


STAGE_LABELS = {
    "received": "已收到客户消息",
    "detecting_language": "识别客户语言中",
    "loading_context": "加载对话上下文中",
    "checking_service_mode": "检查客服模式中",
    "checking_quote_intent": "判断是否报价/人工转接中",
    "loading_scene_state": "读取场景上下文中",
    "loading_products": "加载产品库中",
    "analyzing_scene_request": "解析场景图需求中",
    "resolving_product_reference": "解析商品指代中",
    "scene_bundle_selection": "选择场景搭配商品中",
    "scene_image_generation": "场景图生成中",
    "checking_product_recommendation": "判断商品推荐意图中",
    "product_matching": "匹配推荐商品中",
    "knowledge_retrieval": "检索知识库中",
    "file_matching": "匹配相关文件中",
    "loading_chat_history": "读取历史对话中",
    "llm_generating_answer": "LLM 生成客服回复中",
    "creating_ai_draft": "生成待人工确认草稿中",
    "sending_response": "发送回复中",
    "waiting_human": "等待人工客服处理",
    "completed": "已完成",
    "failed": "处理失败",
}


def _label(stage_key: str, fallback: str | None = None) -> str:
    return fallback or STAGE_LABELS.get(stage_key, stage_key)


async def set_conversation_stage(
    conversation_id: int,
    stage_key: str,
    *,
    stage_label: str | None = None,
    stage_detail: str = "",
    is_processing: bool = True,
) -> None:
    now = datetime.utcnow()
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ConversationProcessingState).where(
                    ConversationProcessingState.conversation_id == conversation_id
                )
            )
            state = result.scalar_one_or_none()
            if not state:
                state = ConversationProcessingState(conversation_id=conversation_id)
                db.add(state)
            state.stage_key = stage_key
            state.stage_label = _label(stage_key, stage_label)
            state.stage_detail = stage_detail[:1000]
            state.is_processing = is_processing
            if is_processing:
                state.started_at = now
            state.updated_at = now
            await db.commit()
    except Exception:
        logger.exception("Failed to update conversation stage conversation_id=%s stage=%s", conversation_id, stage_key)


async def mark_conversation_completed(conversation_id: int, detail: str = "") -> None:
    await set_conversation_stage(
        conversation_id,
        "completed",
        stage_detail=detail,
        is_processing=False,
    )


async def mark_conversation_failed(conversation_id: int, detail: str = "") -> None:
    await set_conversation_stage(
        conversation_id,
        "failed",
        stage_detail=detail,
        is_processing=False,
    )


async def start_turn_metric(
    conversation_id: int,
    *,
    user_message_id: int | None,
    request_text: str,
) -> int | None:
    try:
        async with AsyncSessionLocal() as db:
            metric = ConversationTurnMetric(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_text=(request_text or "")[:4000],
                started_at=datetime.utcnow(),
                success=True,
            )
            db.add(metric)
            await db.commit()
            await db.refresh(metric)
            return metric.id
    except Exception:
        logger.exception("Failed to start turn metric conversation_id=%s", conversation_id)
        return None


async def mark_turn_first_response(metric_id: int | None, response_kind: str) -> None:
    if not metric_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            metric = await db.get(ConversationTurnMetric, metric_id)
            if not metric or metric.first_response_at:
                return
            now = datetime.utcnow()
            metric.response_kind = response_kind
            metric.first_response_at = now
            metric.first_response_ms = int((now - metric.started_at).total_seconds() * 1000)
            await db.commit()
    except Exception:
        logger.exception("Failed to mark first response metric_id=%s", metric_id)


async def mark_turn_intent(
    metric_id: int | None,
    *,
    primary_intent: str,
    confidence: float | None,
    source: str = "",
    secondary_intents: list[str] | None = None,
    reason: str = "",
) -> None:
    if not metric_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            metric = await db.get(ConversationTurnMetric, metric_id)
            if not metric:
                return
            metric.primary_intent = (primary_intent or "")[:100]
            metric.secondary_intents_json = json.dumps(secondary_intents or [], ensure_ascii=False)
            metric.intent_confidence = confidence
            metric.intent_source = (source or "")[:50]
            metric.intent_reason = (reason or "")[:2000]
            await db.commit()
    except Exception:
        logger.exception("Failed to mark turn intent metric_id=%s", metric_id)


async def complete_turn_metric(
    metric_id: int | None,
    *,
    response_kind: str | None = None,
    success: bool = True,
    error_message: str = "",
) -> None:
    if not metric_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            metric = await db.get(ConversationTurnMetric, metric_id)
            if not metric:
                return
            now = datetime.utcnow()
            if response_kind:
                metric.response_kind = response_kind
            if not metric.first_response_at:
                metric.first_response_at = now
                metric.first_response_ms = int((now - metric.started_at).total_seconds() * 1000)
            metric.completed_at = now
            metric.total_ms = int((now - metric.started_at).total_seconds() * 1000)
            metric.success = success
            metric.error_message = (error_message or "")[:2000]
            await db.commit()
    except Exception:
        logger.exception("Failed to complete turn metric metric_id=%s", metric_id)
