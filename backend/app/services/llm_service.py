import asyncio
import json
import logging
import re
import unicodedata
from typing import Any

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from sqlalchemy import select
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import SystemSetting

logger = logging.getLogger(__name__)
settings = get_settings()

LLM_SETTING_KEYS = {
    "llm_provider": "openai",
    "llm_api_key": settings.OPENAI_API_KEY,
    "llm_base_url": settings.OPENAI_BASE_URL,
    "llm_model": settings.OPENAI_MODEL,
    "llm_temperature": "0.7",
    "llm_max_tokens": "1000",
    "embedding_model": settings.EMBEDDING_MODEL,
    "embedding_base_url": settings.OPENAI_BASE_URL,
    "embedding_api_key": "",
    "image_model": "gpt-image-1",
    "image_base_url": settings.OPENAI_BASE_URL,
    "image_api_key": "",
    "image_size": "1024x1024",
    "image_quality": "high",
    "image_style": "natural",
}

_settings_cache: dict[str, str] = {}
_cache_loaded = False


async def load_llm_settings() -> dict[str, str]:
    """Load LLM settings from the database, with defaults as fallback."""
    global _settings_cache, _cache_loaded
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(SystemSetting).where(SystemSetting.key.like("llm_%"))
            )
            rows = result.scalars().all()
            result2 = await db.execute(
                select(SystemSetting).where(SystemSetting.key.like("embedding_%"))
            )
            rows2 = result2.scalars().all()
            result3 = await db.execute(
                select(SystemSetting).where(SystemSetting.key.like("image_%"))
            )
            rows3 = result3.scalars().all()
            db_settings = {r.key: r.value for r in list(rows) + list(rows2) + list(rows3)}

        merged = {}
        for key, default in LLM_SETTING_KEYS.items():
            merged[key] = db_settings.get(key, default) or default
        _settings_cache = merged
        _cache_loaded = True
        return merged
    except Exception as e:
        logger.error(f"Failed to load LLM settings: {e}")
        return dict(LLM_SETTING_KEYS)


async def get_llm_settings() -> dict[str, str]:
    if not _cache_loaded:
        return await load_llm_settings()
    return _settings_cache


def invalidate_llm_cache():
    global _cache_loaded
    _cache_loaded = False


async def save_llm_settings(updates: dict[str, Any]):
    """Persist LLM settings to the database and invalidate cache."""
    async with AsyncSessionLocal() as db:
        for key, value in updates.items():
            if key not in LLM_SETTING_KEYS:
                continue
            existing = await db.get(SystemSetting, key)
            if existing:
                existing.value = str(value)
            else:
                db.add(SystemSetting(key=key, value=str(value)))
        await db.commit()
    invalidate_llm_cache()


def _build_openai_client(cfg: dict[str, str]) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=cfg.get("llm_api_key", ""),
        base_url=cfg.get("llm_base_url", "https://api.openai.com/v1"),
    )


def _build_embedding_client(cfg: dict[str, str]) -> AsyncOpenAI:
    """Embedding always uses the OpenAI-compatible interface."""
    api_key = cfg.get("embedding_api_key") or cfg.get("llm_api_key", "")
    base_url = cfg.get("embedding_base_url") or cfg.get("llm_base_url", "https://api.openai.com/v1")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


def _resolve_embedding_model(base_url: str, model: str | None) -> str:
    configured = (model or "").strip()
    base = (base_url or "").lower()
    if "dashscope" in base and configured in {"", "text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"}:
        return "text-embedding-v4"
    return configured or "text-embedding-3-small"


async def _chat_completion(
    messages: list[dict],
    max_tokens: int | None = None,
    temperature: float | None = None,
    disable_thinking: bool = False,
) -> str:
    """Unified chat completion that routes to the correct provider."""
    cfg = await get_llm_settings()
    provider = cfg.get("llm_provider", "openai").lower()
    model = cfg.get("llm_model", "gpt-4o")
    temp = temperature if temperature is not None else float(cfg.get("llm_temperature", "0.7"))
    mt = max_tokens or int(cfg.get("llm_max_tokens", "1000"))

    if provider == "anthropic":
        return await _anthropic_chat(cfg, messages, model, mt, temp)
    else:
        return await _openai_chat(cfg, messages, model, mt, temp, disable_thinking=disable_thinking)


async def _openai_chat(
    cfg: dict,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
    disable_thinking: bool = False,
) -> str:
    client = _build_openai_client(cfg)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    base_url = (cfg.get("llm_base_url") or "").lower()
    if disable_thinking and "dashscope" in base_url:
        kwargs["extra_body"] = {"enable_thinking": False}
    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content.strip()


async def _anthropic_chat(cfg: dict, messages: list[dict], model: str, max_tokens: int, temperature: float) -> str:
    client = AsyncAnthropic(api_key=cfg.get("llm_api_key", ""))
    system_msg = ""
    user_messages = []
    for m in messages:
        if m["role"] == "system":
            system_msg += m["content"] + "\n"
        else:
            user_messages.append({"role": m["role"], "content": m["content"]})
    if not user_messages:
        user_messages = [{"role": "user", "content": "Hello"}]

    response = await client.messages.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        system=system_msg.strip() if system_msg else "You are a helpful assistant.",
        messages=user_messages,
    )
    return response.content[0].text.strip()


async def get_embedding(text: str) -> list[float]:
    """Get embedding vector for text using the configured embedding provider."""
    cfg = await get_llm_settings()
    client = _build_embedding_client(cfg)
    base_url = cfg.get("embedding_base_url") or cfg.get("llm_base_url", "https://api.openai.com/v1")
    model = _resolve_embedding_model(base_url, cfg.get("embedding_model"))
    try:
        response = await client.embeddings.create(model=model, input=text)
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return []


def build_image_client(cfg: dict[str, str] | None = None) -> AsyncOpenAI:
    cfg = cfg or _settings_cache or LLM_SETTING_KEYS
    api_key = cfg.get("image_api_key") or cfg.get("llm_api_key", "")
    base_url = cfg.get("image_base_url") or cfg.get("llm_base_url", "https://api.openai.com/v1")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


# ─── Public API (used by bot and other services) ─────────────────────────────

def _heuristic_language(text: str) -> str | None:
    """Fast character-based language detection fallback."""
    if re.search(r'[\uac00-\ud7af]', text):
        return "ko"
    if re.search(r'[\u3040-\u30ff\uff66-\uff9f]', text):
        return "ja"
    if re.search(r'[\u4e00-\u9fff]', text):
        return "zh"
    if re.search(r'[\u0600-\u06ff]', text):
        return "ar"
    if re.search(r'[\u0400-\u04ff]', text):
        return "ru"
    return None


INTENT_VALUES = {
    "general_question",
    "quote_handoff",
    "human_handoff",
    "product_recommendation",
    "product_intro",
    "scene_image_request",
    "scene_image_confirmation",
    "file_request",
    "warranty_policy",
    "return_exchange_policy",
    "shipping_delivery",
    "complaint",
    "out_of_scope",
}


def _intent_result(
    primary_intent: str = "general_question",
    confidence: float = 0.0,
    *,
    source: str = "fallback",
    secondary_intents: list[str] | None = None,
    slots: dict[str, Any] | None = None,
    needs_human: bool = False,
    clarification_question: str = "",
    reason: str = "",
) -> dict[str, Any]:
    if primary_intent not in INTENT_VALUES:
        primary_intent = "general_question"
    return {
        "primary_intent": primary_intent,
        "secondary_intents": [x for x in (secondary_intents or []) if x in INTENT_VALUES and x != primary_intent],
        "confidence": max(0.0, min(1.0, float(confidence or 0.0))),
        "slots": {
            "target_product_id": None,
            "scene_name": "",
            "style_hint": "",
            "file_ids": [],
            **(slots or {}),
        },
        "needs_human": bool(needs_human),
        "clarification_question": clarification_question or "",
        "reason": reason or "",
        "source": source,
    }


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start:end + 1]
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _fast_intent_from_rules(text: str, *, has_pending_scene_confirmation: bool = False) -> dict[str, Any] | None:
    normalized = (text or "").strip().lower()
    if not normalized:
        return None
    compact = re.sub(r"\s+", "", normalized).translate(str.maketrans({
        "１": "1",
        "２": "2",
        "３": "3",
        "４": "4",
        "５": "5",
        "６": "6",
        "７": "7",
        "８": "8",
        "９": "9",
        "＃": "#",
        "﹟": "#",
    }))

    def has_any(patterns: list[str]) -> bool:
        return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns)

    if has_any([
        r"转人工", r"人工客服", r"真人", r"人工服务", r"接人工",
        r"\bhuman\b", r"\bagent\b", r"real person", r"representative", r"manual support",
        r"担当者", r"オペレーター", r"人工 상담", r"상담원", r"사람 상담",
        r"agente humano", r"persona real", r"representante", r"agent humain", r"conseiller", r"personne réelle",
    ]):
        return _intent_result("human_handoff", 0.98, source="rules", needs_human=True, reason="explicit human handoff request")

    if has_any([
        r"没用", r"太差", r"差劲", r"垃圾", r"投诉", r"生气", r"不满意", r"糟糕", r"骗人",
        r"useless", r"terrible", r"awful", r"angry", r"complaint", r"not satisfied", r"bad service",
        r"役に立たない", r"ひどい", r"最悪", r"不満", r"苦情",
        r"쓸모없", r"최악", r"불만", r"화가", r"항의",
        r"inútil", r"terrible", r"enojado", r"queja", r"no estoy satisfecho",
        r"inutile", r"mécontent", r"plainte", r"pas satisfait", r"service mauvais",
    ]):
        return _intent_result("complaint", 0.9, source="rules", needs_human=True, reason="complaint or negative sentiment keyword")

    if has_any([
        r"报价", r"价格", r"价钱", r"多少钱", r"费用", r"预算", r"询价", r"采购",
        r"\bprice\b", r"\bpricing\b", r"\bquote\b", r"quotation", r"\bcost\b", r"how much",
        r"価格", r"値段", r"見積", r"いくら", r"費用",
        r"가격", r"견적", r"얼마", r"비용",
        r"precio", r"cotización", r"presupuesto", r"cuánto cuesta", r"coste",
        r"prix", r"devis", r"combien", r"coût", r"budget",
    ]):
        return _intent_result("quote_handoff", 0.95, source="rules", needs_human=True, reason="pricing or quotation keyword")

    if has_pending_scene_confirmation and (
        re.fullmatch(r"#?[1-9]", compact)
        or re.fullmatch(r"第?#?[1-9](?:个|款|件|号)?", compact)
        or re.fullmatch(r"第?[一二三四五六七八九](?:个|款|件|号)?", compact)
        or re.fullmatch(r"(?:no\.?|number|num|nº)[1-9]", compact)
        or compact in {
            "first", "1st", "second", "2nd", "third", "3rd",
            "primero", "primera", "segundo", "segunda", "tercero", "tercera",
            "premier", "premiere", "deuxieme", "troisieme",
            "첫번째", "두번째", "세번째",
            "一番目", "二番目", "三番目",
        }
    ):
        return _intent_result("scene_image_confirmation", 0.9, source="rules", reason="product selection after recommendation")

    if has_pending_scene_confirmation and has_any([
        r"^好$", r"^可以$", r"^要$", r"^是$", r"^yes$", r"^ok$", r"^sure$",
        r"想看看", r"生成", r"来一?张", r"看.*效果", r"show me", r"generate",
    ]):
        return _intent_result("scene_image_confirmation", 0.88, source="rules", reason="scene confirmation after recommendation")

    if has_any([
        r"场景图", r"效果图", r"搭配图", r"实景", r"渲染", r"空间效果", r"摆在.*(客厅|卧室|餐厅|书房)",
        r"scene image", r"render", r"showroom", r"styled image", r"effect image", r"in (a|the).*(room|living room|bedroom|dining room)",
    ]):
        return _intent_result("scene_image_request", 0.9, source="rules", reason="scene image keyword")

    if has_any([
        r"保修", r"质保", r"售后", r"保固", r"维修", r"坏了怎么办",
        r"\bwarranty\b", r"\bguarantee\b", r"after[- ]?sales", r"repair policy",
        r"保証", r"アフターサービス", r"수리", r"보증", r"garantía", r"garantie",
    ]):
        return _intent_result("warranty_policy", 0.88, source="rules", reason="warranty or after-sales keyword")

    if has_any([
        r"退换货", r"退货", r"换货", r"退款", r"退换", r"退订",
        r"\breturn\b", r"\bexchange\b", r"\brefund\b", r"return policy", r"exchange policy",
        r"返品", r"交換", r"返金", r"반품", r"교환", r"환불",
        r"devolución", r"cambio", r"reembolso", r"retour", r"échange", r"remboursement",
    ]):
        return _intent_result("return_exchange_policy", 0.9, source="rules", reason="return or exchange policy keyword")

    if has_any([
        r"物流", r"配送", r"发货", r"送货", r"运费", r"多久到", r"什么时候到",
        r"\bshipping\b", r"\bdelivery\b", r"freight", r"lead time", r"when.*arrive",
        r"配送", r"送料", r"配達", r"배송", r"운송", r"envío", r"entrega", r"livraison",
    ]):
        return _intent_result("shipping_delivery", 0.86, source="rules", reason="shipping or delivery keyword")

    if has_any([
        r"介绍", r"讲讲", r"说明一下", r"特点", r"材质", r"尺寸", r"规格", r"参数", r"适合",
        r"tell me about", r"introduce", r"details", r"features", r"material", r"size", r"dimensions", r"specs",
        r"紹介", r"特徴", r"素材", r"サイズ", r"상세", r"특징", r"소재", r"크기",
        r"presentar", r"características", r"material", r"tamaño", r"présenter", r"caractéristiques", r"dimensions",
    ]):
        return _intent_result("product_intro", 0.82, source="rules", reason="product introduction or detail keyword")

    if has_any([
        r"推荐", r"有哪些", r"有什么.*(产品|沙发|床|桌|椅|柜)", r"产品图", r"款式", r"看看.*(产品|沙发|床|桌|椅|柜)",
        r"recommend", r"show me.*(product|sofa|bed|table|chair|cabinet)", r"what.*(products|sofas|chairs).*have",
    ]):
        return _intent_result("product_recommendation", 0.84, source="rules", reason="product browsing or recommendation keyword")

    if has_any([
        r"资料", r"文件", r"手册", r"说明书", r"目录", r"catalog", r"brochure", r"manual", r"pdf", r"document", r"file",
    ]):
        return _intent_result("file_request", 0.82, source="rules", reason="file or document request keyword")

    return None


def _product_router_context(products: list[dict] | None, recent_product_ids: list[int] | None) -> str:
    products = products or []
    recent_product_ids = recent_product_ids or []
    products_by_id = {int(p["id"]): p for p in products if p.get("id") is not None}
    recent = [products_by_id[pid] for pid in recent_product_ids if pid in products_by_id]
    recent_lines = [
        f"SLOT:{idx} | ID:{p['id']} | {p.get('name', '')} | space:{p.get('space', '')} | style:{p.get('style', '')}"
        for idx, p in enumerate(recent, start=1)
    ]
    catalog_lines = [
        f"ID:{p['id']} | {p.get('name', '')} | space:{p.get('space', '')} | style:{p.get('style', '')} | material:{p.get('material', '')}"
        for p in products[:80]
    ]
    return (
        f"Recent recommended products:\n{chr(10).join(recent_lines) or '(none)'}\n\n"
        f"Product catalog sample:\n{chr(10).join(catalog_lines) or '(none)'}"
    )


def classify_customer_intent_fast(
    user_message: str,
    *,
    has_pending_scene_confirmation: bool = False,
) -> dict[str, Any] | None:
    """Return a high-confidence local-rule intent without calling the LLM."""
    return _fast_intent_from_rules(
        user_message,
        has_pending_scene_confirmation=has_pending_scene_confirmation,
    )


async def classify_customer_intent(
    user_message: str,
    *,
    products: list[dict] | None = None,
    recent_product_ids: list[int] | None = None,
    has_pending_scene_confirmation: bool = False,
    chat_history: list[dict] | None = None,
) -> dict[str, Any]:
    """Classify the next customer intent once, with a fast rules path before LLM routing."""
    fast = _fast_intent_from_rules(
        user_message,
        has_pending_scene_confirmation=has_pending_scene_confirmation,
    )
    if fast:
        return fast

    if not user_message or len(user_message.strip()) < 2:
        return _intent_result("general_question", 0.3, source="rules", reason="empty or too short")

    prompt = (
        "You are the intent router for a furniture customer-service agent.\n"
        "Classify the customer's latest message into exactly one primary intent and optional secondary intents.\n"
        "Allowed intents:\n"
        "- quote_handoff: pricing, quotation, purchase cost, quote request. High-risk; usually needs human.\n"
        "- human_handoff: customer explicitly asks for a human/support representative.\n"
        "- product_recommendation: browsing products, asking what products are available, product photos, recommendations.\n"
        "- product_intro: asks about a specific product's features, material, size, specs, usage, or introduction.\n"
        "- scene_image_request: wants a product shown in a styled scene/render/showroom/effect image.\n"
        "- scene_image_confirmation: confirms a previous offer to generate scene images.\n"
        "- file_request: asks for catalog, brochure, manual, PDF, document, spec sheet, or file.\n"
        "- warranty_policy: asks about warranty, after-sales service, repair, guarantee, or quality coverage.\n"
        "- return_exchange_policy: asks about returns, exchanges, refunds, cancellation, or related policy.\n"
        "- shipping_delivery: asks about shipping, delivery, freight, lead time, or arrival time.\n"
        "- complaint: angry, dissatisfied, says the answer is useless, or threatens complaint.\n"
        "- out_of_scope: unrelated or unsupported request.\n"
        "- general_question: normal FAQ, product/policy question, or anything else.\n\n"
        "Edge handling hints:\n"
        "- Put pricing/human_handoff/complaint in secondary_intents if they appear together with another request.\n"
        "- Use a useful clarification_question when the request is vague or under-specified.\n"
        "- If the user asks several things at once, make the most urgent/high-risk item primary and put the rest in secondary_intents.\n\n"
        "Return ONLY compact JSON with this shape:\n"
        '{"primary_intent":"general_question","secondary_intents":[],"confidence":0.0,'
        '"slots":{"target_product_id":null,"scene_name":"","style_hint":"","file_ids":[]},'
        '"needs_human":false,"clarification_question":"","reason":""}\n'
        "Confidence must be 0-1. Use lower confidence when ambiguous. For scene requests, extract scene_name, "
        "style_hint, and target_product_id if clear from recent products or catalog.\n\n"
        f"Pending scene confirmation: {has_pending_scene_confirmation}\n"
        f"{_product_router_context(products, recent_product_ids)}"
    )
    convo_messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
    if chat_history:
        for msg in chat_history[-6:]:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role in {"user", "assistant"} and content:
                convo_messages.append({"role": role, "content": content})
    convo_messages.append({"role": "user", "content": user_message})

    try:
        raw = await _chat_completion(
            messages=convo_messages,
            max_tokens=220,
            temperature=0,
            disable_thinking=True,
        )
        data = _extract_json_object(raw)
        slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        target_id = slots.get("target_product_id")
        if target_id is not None:
            try:
                target_id = int(target_id)
            except (TypeError, ValueError):
                target_id = None
        slots["target_product_id"] = target_id
        file_ids = slots.get("file_ids")
        slots["file_ids"] = file_ids if isinstance(file_ids, list) else []
        return _intent_result(
            str(data.get("primary_intent") or "general_question"),
            float(data.get("confidence") or 0.0),
            source="llm_router",
            secondary_intents=data.get("secondary_intents") if isinstance(data.get("secondary_intents"), list) else [],
            slots=slots,
            needs_human=bool(data.get("needs_human")),
            clarification_question=str(data.get("clarification_question") or ""),
            reason=str(data.get("reason") or ""),
        )
    except Exception as e:
        logger.error(f"Intent classification failed: {e}")
        return _intent_result("general_question", 0.0, reason="intent classifier failed")

async def detect_language(text: str) -> str:
    heuristic = _heuristic_language(text)
    if heuristic:
        return heuristic
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a language detector. Return ONLY the ISO 639-1 language code "
                        "(e.g., 'en', 'zh', 'ja', 'ko', 'es', 'fr', 'de', 'ar', 'ru', 'pt'). "
                        "Treat any text containing hiragana or katakana as 'ja' even if it also "
                        "contains Chinese kanji. Treat hangul as 'ko'. Nothing else."
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=5,
            temperature=0,
            disable_thinking=True,
        )
        return result.strip().lower()[:2]
    except Exception as e:
        logger.error(f"Language detection failed: {e}")
        return "en"


async def check_is_quote_related(text: str) -> bool:
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Determine if the user's message is related to pricing, quotation, "
                        "cost inquiry, purchasing, or requesting a quote. "
                        'Return JSON: {"is_quote": true} or {"is_quote": false}. Nothing else.'
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=20,
            temperature=0,
            disable_thinking=True,
        )
        parsed = json.loads(result)
        return parsed.get("is_quote", False)
    except Exception as e:
        logger.error(f"Quote detection failed: {e}")
        return False


async def check_file_request(text: str, available_files: list[dict]) -> list[int]:
    """Determine if the user is requesting files; return matching file IDs."""
    if not available_files:
        return []
    file_list = "\n".join(
        f"- ID:{f['id']} | {f['name']} | {f['description']} | tags: {f['tags']} | mime: {f.get('mime_type') or ''}"
        for f in available_files
    )
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You match customer requests to available files. "
                        "Given the customer message and a file catalog, return a JSON array of "
                        "file IDs that are relevant. Return [] if none match.\n"
                        "Return ONLY the JSON array, e.g. [1,3]. Nothing else.\n\n"
                        f"File catalog:\n{file_list}"
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=50,
            temperature=0,
            disable_thinking=True,
        )
        return json.loads(result)
    except Exception as e:
        logger.error(f"File request detection failed: {e}")
        return []


async def check_is_product_recommendation(text: str) -> bool:
    """Detect if the user wants product recommendations, browsing, or product photos."""
    if not text or len(text.strip()) < 2:
        return False
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Determine if the user's message is about browsing products, asking for "
                        "product recommendations, wanting to see product photos/images, or asking "
                        "what products are available. Examples: 'recommend a sofa', 'what chairs "
                        "do you have', 'show me living room furniture', '有什么沙发', '推荐一款椅子', "
                        "'发一下产品图', '有哪些款式', 'send me a photo of the chair'. "
                        'Return JSON: {"is_product_rec": true} or {"is_product_rec": false}. Nothing else.'
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=20,
            temperature=0,
            disable_thinking=True,
        )
        return json.loads(result).get("is_product_rec", False)
    except Exception as e:
        logger.error(f"Product recommendation detection failed: {e}")
        return False


async def check_is_scene_image_confirmation(text: str) -> bool:
    if not text or len(text.strip()) < 1:
        return False
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Determine whether the user's message is confirming that they want scene images, "
                        "effect renders, showroom images, or styled display images after the assistant asked "
                        "if such images are needed. Examples: 'yes', 'show me', '要效果图', '来几张场景图', "
                        "'please generate it', '想看看'. "
                        'Return JSON: {"is_confirmed": true} or {"is_confirmed": false}. Nothing else.'
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=20,
            temperature=0,
            disable_thinking=True,
        )
        return json.loads(result).get("is_confirmed", False)
    except Exception as e:
        logger.error(f"Scene image confirmation detection failed: {e}")
        return False


async def resolve_recent_product_reference(
    user_message: str,
    products: list[dict],
    recent_product_ids: list[int] | None = None,
) -> dict[str, Any]:
    if not user_message or len(user_message.strip()) < 1:
        return {"target_product_id": None, "reason": ""}

    recent_product_ids = recent_product_ids or []
    if not recent_product_ids:
        return {"target_product_id": None, "reason": ""}

    products_by_id = {
        int(p["id"]): p for p in products
        if p.get("id") is not None
    }
    recent_products = [products_by_id[pid] for pid in recent_product_ids if pid in products_by_id]
    if not recent_products:
        return {"target_product_id": None, "reason": ""}

    recent_lines = "\n".join(
        f"SLOT:{idx} | ID:{p['id']} | {p['name']} | 空间:{p.get('space', '')} | 风格:{p.get('style', '')}"
        for idx, p in enumerate(recent_products, start=1)
    )
    prompt = (
        "The assistant previously recommended these products to the customer.\n"
        "Determine whether the customer's latest message refers to one specific recommended product.\n"
        "The customer may speak in ANY language. They may refer by product name, slot number like #1/#2/#3, "
        "Arabic numerals, ordinal words, or phrases like 'the last one'.\n"
        "Return ONLY JSON with keys: target_product_id (number or null), reason (string).\n\n"
        f"Recent recommended products:\n{recent_lines}"
    )
    try:
        raw = await _chat_completion(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=120,
            temperature=0,
            disable_thinking=True,
        )
        data = json.loads(raw)
        target_id = data.get("target_product_id")
        if target_id is not None:
            try:
                target_id = int(target_id)
            except (TypeError, ValueError):
                target_id = None
        valid_ids = {int(p["id"]) for p in recent_products}
        if target_id not in valid_ids:
            target_id = None
        return {
            "target_product_id": target_id,
            "reason": str(data.get("reason") or ""),
        }
    except Exception as e:
        logger.error(f"Recent product reference resolution failed: {e}")
        return {"target_product_id": None, "reason": ""}


async def analyze_scene_image_request(
    user_message: str,
    products: list[dict],
    recent_product_ids: list[int] | None = None,
) -> dict[str, Any]:
    if not user_message or len(user_message.strip()) < 2:
        return {
            "is_scene_request": False,
            "scene_name": "",
            "style_hint": "",
            "target_product_id": None,
            "reason": "",
        }

    recent_product_ids = recent_product_ids or []
    recent_lines = []
    for p in products:
        if p.get("id") in recent_product_ids:
            recent_lines.append(
                f"SLOT:{len(recent_lines) + 1} | ID:{p['id']} | {p['name']} | 空间:{p.get('space', '')} | 风格:{p.get('style', '')}"
            )
    catalog = "\n".join(
        f"ID:{p['id']} | {p['name']} | 空间:{p.get('space', '')} | 风格:{p.get('style', '')} | 材质:{p.get('material', '')}"
        for p in products[:120]
    )
    prompt = (
        "Analyze whether the customer is asking to see a product in a realistic scene, effect image, "
        "showroom render, or styled environment. This includes messages like 'show me this sofa in a Chinese-style living room'.\n"
        "If they refer to 'this product/this sofa/this one', prefer the recent recommended products if applicable.\n"
        "The customer may speak in ANY language and may refer to products by name, slot number like #1/#2/#3, numerals, or ordinals.\n"
        "Return ONLY JSON with keys: is_scene_request (bool), scene_name (string), style_hint (string), "
        "target_product_id (number or null), reason (string).\n\n"
        f"Recent recommended products:\n{chr(10).join(recent_lines) or '(none)'}\n\n"
        f"Catalog:\n{catalog}"
    )
    try:
        raw = await _chat_completion(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=200,
            temperature=0,
            disable_thinking=True,
        )
        data = json.loads(raw)
        target_id = data.get("target_product_id")
        if target_id is not None:
            try:
                data["target_product_id"] = int(target_id)
            except (TypeError, ValueError):
                data["target_product_id"] = None
        return {
            "is_scene_request": bool(data.get("is_scene_request")),
            "scene_name": str(data.get("scene_name") or ""),
            "style_hint": str(data.get("style_hint") or ""),
            "target_product_id": data.get("target_product_id"),
            "reason": str(data.get("reason") or ""),
        }
    except Exception as e:
        logger.error(f"Scene request analysis failed: {e}")
        return {
            "is_scene_request": False,
            "scene_name": "",
            "style_hint": "",
            "target_product_id": None,
            "reason": "",
        }


async def select_scene_bundle_products(
    user_message: str,
    primary_product: dict[str, Any],
    candidate_products: list[dict[str, Any]],
    scene_name: str,
    style_hint: str,
) -> list[int]:
    if not candidate_products:
        return []
    catalog = "\n".join(
        f"ID:{p['id']} | 品牌:{p.get('brand', '')} | {p['name']} | 类别:{p.get('category', '')} | 空间:{p.get('space', '')} | 风格:{p.get('style', '')} | 材质:{p.get('material', '')}"
        for p in candidate_products[:50]
    )
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are selecting complementary furniture products for a styled scene image.\n"
                        "Choose up to 3 products that match the primary product and scene.\n"
                        "Prioritize products that fit the same room and style and can logically appear together.\n"
                        "Every complementary product MUST be a different product category from the main product.\n"
                        "Never choose another sofa for a sofa, another bed for a bed, another dining table for a dining table, etc.\n"
                        "Return ONLY a JSON array of numeric IDs, e.g. [12, 18].\n\n"
                        f"Primary product: 品牌:{primary_product.get('brand', '')} | {primary_product['name']} | 空间:{primary_product.get('space', '')} "
                        f"| 风格:{primary_product.get('style', '')} | 材质:{primary_product.get('material', '')} | 类别:{primary_product.get('category', '')}\n"
                        f"Requested scene: {scene_name}\n"
                        f"Style hint: {style_hint}\n"
                        f"Candidate catalog:\n{catalog}"
                    ),
                },
                {"role": "user", "content": user_message or primary_product["name"]},
            ],
            max_tokens=120,
            temperature=0,
            disable_thinking=True,
        )
        ids = json.loads(result)
        if not isinstance(ids, list):
            return []
        valid_ids = {int(p["id"]) for p in candidate_products}
        out: list[int] = []
        for x in ids:
            try:
                val = int(x)
            except (TypeError, ValueError):
                continue
            if val in valid_ids and val not in out:
                out.append(val)
        return out[:3]
    except Exception as e:
        logger.error(f"Scene bundle product selection failed: {e}")
        return []


PRODUCT_MATCH_CANDIDATE_LIMIT = 30
PRODUCT_MATCH_LLM_TIMEOUT_SECONDS = 8

PRODUCT_CATEGORY_TERMS = {
    "sofa": ["沙发", "沙發", "贵妃", "躺椅", "sofa", "couch", "sectional", "recliner", "loveseat", "ソファ", "ソファー", "カウチ", "소파", "쇼파", "sofa", "sofa", "canape", "divan"],
    "dining_table": ["餐桌", "饭桌", "餐台", "dining table", "dining desk", "mesa de comedor", "table a manger", "table de salle a manger", "ダイニングテーブル", "食卓", "식탁"],
    "dining_chair": ["餐椅", "饭椅", "dining chair", "silla de comedor", "chaise de salle a manger", "ダイニングチェア", "食卓椅", "식탁 의자"],
    "bed": ["床", "双人床", "单人床", "bed", "cama", "lit", "ベッド", "침대"],
    "nightstand": ["床头柜", "床頭櫃", "nightstand", "bedside table", "mesita de noche", "mesa de noche", "table de chevet", "ナイトテーブル", "ベッドサイド", "협탁"],
    "coffee_table": ["茶几", "茶桌", "茶台", "边几", "角几", "tea table", "coffee table", "side table", "end table", "mesa de centro", "mesa auxiliar", "table basse", "table d'appoint", "ローテーブル", "サイドテーブル", "커피 테이블", "사이드 테이블"],
    "tv_cabinet": ["电视柜", "電視櫃", "电视机柜", "tv cabinet", "tv stand", "media console", "mueble tv", "meuble tv", "テレビ台", "tvボード", "거실장", "tv장"],
    "cabinet": ["柜", "储物柜", "收纳柜", "边柜", "斗柜", "cabinet", "storage cabinet", "commode", "dresser", "aparador", "armario", "buffet", "rangement", "キャビネット", "収納", "수납장", "서랍장"],
    "wardrobe": ["衣柜", "衣櫃", "wardrobe", "closet", "armoire", "armario ropero", "クローゼット", "ワードローブ", "옷장"],
    "desk": ["书桌", "办公桌", "desk", "office desk", "bureau", "escritorio", "デスク", "机", "책상"],
    "bookshelf": ["书柜", "书架", "书橱", "bookcase", "bookshelf", "bibliotheque", "estanteria", "本棚", "書棚", "책장", "책꽂이"],
    "bar": ["吧台", "吧椅", "bar table", "bar stool", "barra", "taburete", "table de bar", "bar", "バーテーブル", "바 테이블", "바 의자"],
    "chair": ["椅", "椅子", "休闲椅", "单椅", "chair", "armchair", "silla", "fauteuil", "chaise", "チェア", "椅子", "의자"],
}

PRODUCT_SPACE_TERMS = {
    "living_room": ["客厅", "起居室", "living room", "sala", "sala de estar", "salon", "リビング", "居間", "거실"],
    "dining_room": ["餐厅", "饭厅", "dining room", "comedor", "salle a manger", "ダイニング", "식당", "다이닝룸"],
    "bedroom": ["卧室", "主卧", "bedroom", "dormitorio", "chambre", "寝室", "ベッドルーム", "침실"],
    "study": ["书房", "办公室", "study", "office", "bureau", "estudio", "書斎", "オフィス", "서재", "사무실"],
    "entryway": ["玄关", "门厅", "entryway", "foyer", "entree", "recibidor", "玄関", "현관"],
}

PRODUCT_STYLE_TERMS = {
    "modern": ["现代", "现代简约", "modern", "contemporary", "moderno", "moderne", "モダン", "現代", "현대", "모던"],
    "minimalist": ["极简", "简约", "minimalist", "minimal", "minimale", "minimalista", "ミニマル", "シンプル", "미니멀", "심플"],
    "luxury": ["轻奢", "高端", "奢华", "luxury", "premium", "lujo", "lujoso", "luxe", "ラグジュアリー", "高級", "럭셔리", "고급"],
    "nordic": ["北欧", "nordic", "scandinavian", "escandinavo", "scandinave", "北欧", "북유럽"],
    "chinese": ["中式", "新中式", "chinese style", "oriental", "estilo chino", "style chinois", "中国風", "중식", "중국식"],
    "japanese": ["日式", "原木风", "japanese", "japandi", "japones", "japonais", "和風", "日本風", "일본식"],
    "vintage": ["复古", "中古", "retro", "vintage", "clasico", "classique", "レトロ", "ヴィンテージ", "복고", "빈티지"],
    "french": ["法式", "french", "frances", "francais", "フレンチ", "프렌치"],
    "italian": ["意式", "italian", "italiano", "italien", "イタリアン", "이탈리안"],
}

PRODUCT_COLOR_TERMS = {
    "white": ["白", "白色", "米白", "奶油", "象牙", "ivory", "white", "cream", "blanco", "blanca", "blanc", "blanche", "白い", "ホワイト", "흰색", "하얀", "화이트"],
    "black": ["黑", "黑色", "雅黑", "black", "negro", "noir", "黒", "ブラック", "검정", "검은색", "블랙"],
    "gray": ["灰", "灰色", "银灰", "grey", "gray", "gris", "グレー", "灰色", "회색", "그레이"],
    "brown": ["棕", "棕色", "咖啡", "褐色", "brown", "cafe", "marron", "brun", "ブラウン", "茶色", "갈색", "브라운"],
    "wood": ["原木", "木色", "胡桃", "柚木", "樱桃木", "walnut", "teak", "cherry wood", "wood", "madera", "bois", "木目", "ウッド", "원목", "월넛"],
    "red": ["红", "红色", "酒红", "red", "rojo", "rouge", "赤", "レッド", "빨간", "빨강", "레드"],
    "blue": ["蓝", "蓝色", "blue", "azul", "bleu", "青", "ブルー", "파란", "파랑", "블루"],
    "green": ["绿", "绿色", "green", "verde", "vert", "緑", "グリーン", "초록", "녹색", "그린"],
    "purple": ["紫", "紫色", "purple", "violet", "morado", "morada", "violeta", "violet", "violette", "紫", "パープル", "보라", "보라색", "퍼플"],
    "pink": ["粉", "粉色", "pink", "rosa", "rose", "ピンク", "분홍", "핑크"],
    "yellow": ["黄", "黄色", "yellow", "amarillo", "jaune", "黄色", "イエロー", "노랑", "옐로우"],
    "beige": ["米色", "杏色", "卡其", "beige", "khaki", "arena", "ベージュ", "베이지"],
}

PRODUCT_MATERIAL_TERMS = {
    "leather": ["真皮", "牛皮", "皮", "leather", "piel", "cuero", "cuir", "革", "レザー", "가죽"],
    "fabric": ["布艺", "布", "绒", "fabric", "cloth", "tela", "textil", "tissu", "ファブリック", "布", "패브릭", "원단"],
    "solid_wood": ["实木", "原木", "solid wood", "madera maciza", "bois massif", "無垢材", "木製", "원목"],
    "walnut": ["胡桃", "黑胡桃", "walnut", "nogal", "noyer", "ウォールナット", "월넛"],
    "teak": ["柚木", "teak", "teca", "teck", "チーク", "티크"],
    "stone": ["岩板", "大理石", "石", "slate", "marble", "stone", "piedra", "marbre", "セラミック", "大理石", "암판", "대리석"],
    "metal": ["金属", "五金", "metal", "metalico", "metal", "メタル", "金属", "금속"],
}

PRODUCT_BRAND_TERMS = {
    "landbond": ["联邦", "联邦家私", "landbond"],
    "redapple": ["红苹果", "紅蘋果", "red apple", "redapple"],
    "zuoyou": ["左右", "左右沙发", "左右家居", "zuoyou", "zuo you"],
}

PRODUCT_MATCH_TABLES = {
    "categories": PRODUCT_CATEGORY_TERMS,
    "spaces": PRODUCT_SPACE_TERMS,
    "styles": PRODUCT_STYLE_TERMS,
    "colors": PRODUCT_COLOR_TERMS,
    "materials": PRODUCT_MATERIAL_TERMS,
    "brands": PRODUCT_BRAND_TERMS,
}

PRODUCT_MATCH_WEIGHTS = {
    "categories": 80,
    "brands": 32,
    "materials": 28,
    "colors": 24,
    "styles": 22,
    "spaces": 18,
}

PRODUCT_MATCH_VALUE_LABELS = {
    "categories": {
        "sofa": {"zh": "沙发", "en": "sofa", "ja": "ソファ", "ko": "소파", "es": "sofá", "fr": "canapé"},
        "dining_table": {"zh": "餐桌", "en": "dining table", "ja": "ダイニングテーブル", "ko": "식탁", "es": "mesa de comedor", "fr": "table à manger"},
        "dining_chair": {"zh": "餐椅", "en": "dining chair", "ja": "ダイニングチェア", "ko": "식탁 의자", "es": "silla de comedor", "fr": "chaise de salle à manger"},
        "bed": {"zh": "床", "en": "bed", "ja": "ベッド", "ko": "침대", "es": "cama", "fr": "lit"},
        "nightstand": {"zh": "床头柜", "en": "nightstand", "ja": "ナイトテーブル", "ko": "협탁", "es": "mesita de noche", "fr": "table de chevet"},
        "coffee_table": {"zh": "茶几", "en": "coffee table", "ja": "ローテーブル", "ko": "커피 테이블", "es": "mesa de centro", "fr": "table basse"},
        "tv_cabinet": {"zh": "电视柜", "en": "TV cabinet", "ja": "テレビ台", "ko": "거실장", "es": "mueble TV", "fr": "meuble TV"},
        "cabinet": {"zh": "柜类", "en": "cabinet", "ja": "キャビネット", "ko": "수납장", "es": "armario", "fr": "rangement"},
        "wardrobe": {"zh": "衣柜", "en": "wardrobe", "ja": "ワードローブ", "ko": "옷장", "es": "armario ropero", "fr": "armoire"},
        "desk": {"zh": "书桌", "en": "desk", "ja": "デスク", "ko": "책상", "es": "escritorio", "fr": "bureau"},
        "bookshelf": {"zh": "书柜", "en": "bookcase", "ja": "本棚", "ko": "책장", "es": "estantería", "fr": "bibliothèque"},
        "bar": {"zh": "吧台/吧椅", "en": "bar furniture", "ja": "バーファニチャー", "ko": "바 가구", "es": "mueble de bar", "fr": "meuble de bar"},
        "chair": {"zh": "椅子", "en": "chair", "ja": "チェア", "ko": "의자", "es": "silla", "fr": "chaise"},
    },
    "spaces": {
        "living_room": {"zh": "客厅", "en": "living-room", "ja": "リビング", "ko": "거실", "es": "sala de estar", "fr": "salon"},
        "dining_room": {"zh": "餐厅", "en": "dining-room", "ja": "ダイニング", "ko": "식당", "es": "comedor", "fr": "salle à manger"},
        "bedroom": {"zh": "卧室", "en": "bedroom", "ja": "寝室", "ko": "침실", "es": "dormitorio", "fr": "chambre"},
        "study": {"zh": "书房", "en": "study", "ja": "書斎", "ko": "서재", "es": "estudio", "fr": "bureau"},
        "entryway": {"zh": "玄关", "en": "entryway", "ja": "玄関", "ko": "현관", "es": "recibidor", "fr": "entrée"},
    },
    "styles": {
        "modern": {"zh": "现代", "en": "modern", "ja": "モダン", "ko": "모던", "es": "moderno", "fr": "moderne"},
        "minimalist": {"zh": "简约", "en": "minimalist", "ja": "ミニマル", "ko": "미니멀", "es": "minimalista", "fr": "minimaliste"},
        "luxury": {"zh": "轻奢", "en": "luxury", "ja": "ラグジュアリー", "ko": "럭셔리", "es": "lujoso", "fr": "luxe"},
        "nordic": {"zh": "北欧", "en": "Nordic", "ja": "北欧", "ko": "북유럽", "es": "escandinavo", "fr": "scandinave"},
        "chinese": {"zh": "中式", "en": "Chinese-style", "ja": "中国風", "ko": "중국식", "es": "estilo chino", "fr": "style chinois"},
        "japanese": {"zh": "日式", "en": "Japanese-style", "ja": "和風", "ko": "일본식", "es": "japonés", "fr": "japonais"},
        "vintage": {"zh": "复古", "en": "vintage", "ja": "ヴィンテージ", "ko": "빈티지", "es": "vintage", "fr": "vintage"},
        "french": {"zh": "法式", "en": "French-style", "ja": "フレンチ", "ko": "프렌치", "es": "francés", "fr": "français"},
        "italian": {"zh": "意式", "en": "Italian-style", "ja": "イタリアン", "ko": "이탈리안", "es": "italiano", "fr": "italien"},
    },
    "colors": {
        "white": {"zh": "白色", "en": "white", "ja": "白", "ko": "흰색", "es": "blanco", "fr": "blanc"},
        "black": {"zh": "黑色", "en": "black", "ja": "黒", "ko": "검정", "es": "negro", "fr": "noir"},
        "gray": {"zh": "灰色", "en": "gray", "ja": "グレー", "ko": "회색", "es": "gris", "fr": "gris"},
        "brown": {"zh": "棕色", "en": "brown", "ja": "ブラウン", "ko": "갈색", "es": "marrón", "fr": "brun"},
        "wood": {"zh": "木色", "en": "wood-tone", "ja": "木目", "ko": "원목색", "es": "madera", "fr": "bois"},
        "red": {"zh": "红色", "en": "red", "ja": "赤", "ko": "빨강", "es": "rojo", "fr": "rouge"},
        "blue": {"zh": "蓝色", "en": "blue", "ja": "青", "ko": "파랑", "es": "azul", "fr": "bleu"},
        "green": {"zh": "绿色", "en": "green", "ja": "緑", "ko": "초록", "es": "verde", "fr": "vert"},
        "purple": {"zh": "紫色", "en": "purple", "ja": "紫", "ko": "보라색", "es": "morado", "fr": "violet"},
        "pink": {"zh": "粉色", "en": "pink", "ja": "ピンク", "ko": "핑크", "es": "rosa", "fr": "rose"},
        "yellow": {"zh": "黄色", "en": "yellow", "ja": "黄色", "ko": "노랑", "es": "amarillo", "fr": "jaune"},
        "beige": {"zh": "米色", "en": "beige", "ja": "ベージュ", "ko": "베이지", "es": "beige", "fr": "beige"},
    },
    "materials": {
        "leather": {"zh": "皮质", "en": "leather", "ja": "レザー", "ko": "가죽", "es": "cuero", "fr": "cuir"},
        "fabric": {"zh": "布艺", "en": "fabric", "ja": "ファブリック", "ko": "패브릭", "es": "tela", "fr": "tissu"},
        "solid_wood": {"zh": "实木", "en": "solid wood", "ja": "無垢材", "ko": "원목", "es": "madera maciza", "fr": "bois massif"},
        "walnut": {"zh": "胡桃木", "en": "walnut", "ja": "ウォールナット", "ko": "월넛", "es": "nogal", "fr": "noyer"},
        "teak": {"zh": "柚木", "en": "teak", "ja": "チーク", "ko": "티크", "es": "teca", "fr": "teck"},
        "stone": {"zh": "石材/岩板", "en": "stone", "ja": "石材", "ko": "석재", "es": "piedra", "fr": "pierre"},
        "metal": {"zh": "金属", "en": "metal", "ja": "メタル", "ko": "금속", "es": "metal", "fr": "métal"},
    },
    "brands": {
        "landbond": {"zh": "联邦家私", "en": "Landbond", "ja": "Landbond", "ko": "Landbond", "es": "Landbond", "fr": "Landbond"},
        "redapple": {"zh": "红苹果", "en": "Red Apple", "ja": "Red Apple", "ko": "Red Apple", "es": "Red Apple", "fr": "Red Apple"},
        "zuoyou": {"zh": "左右家居", "en": "Zuoyou", "ja": "Zuoyou", "ko": "Zuoyou", "es": "Zuoyou", "fr": "Zuoyou"},
    },
}

PRODUCT_MATCH_STRICT_DIMENSIONS = ("colors", "styles", "materials", "brands", "spaces")
PRODUCT_MATCH_SUPPORTED_LANGUAGES = {"zh", "en", "ja", "ko", "es", "fr"}


def _normalize_match_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).lower()
    without_marks = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
    spaced = re.sub(r"[\s\-_、，,./|:;；：()\[\]{}]+", " ", without_marks)
    return re.sub(r"\s+", " ", spaced).strip()


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(_normalize_match_text(term) in text for term in terms if term)


def _extract_product_query_profile(user_message: str) -> dict[str, set[str]]:
    text = _normalize_match_text(user_message)
    profile: dict[str, set[str]] = {dimension: set() for dimension in PRODUCT_MATCH_TABLES}
    for dimension, table in PRODUCT_MATCH_TABLES.items():
        for key, terms in table.items():
            if _contains_any(text, terms):
                profile[dimension].add(key)
    return profile


def _extract_product_query_terms(user_message: str) -> list[str]:
    text = _normalize_match_text(user_message)
    matched: list[str] = []
    for table in PRODUCT_MATCH_TABLES.values():
        for terms in table.values():
            for term in terms:
                normalized = _normalize_match_text(term)
                if len(normalized) < 2:
                    continue
                if normalized in text and normalized not in matched:
                    matched.append(normalized)
    matched.sort(key=len, reverse=True)
    return matched[:8]


def _product_match_text(product: dict[str, Any]) -> str:
    values = [
        product.get("brand", ""),
        product.get("name", ""),
        product.get("series", ""),
        product.get("space", ""),
        product.get("style", ""),
        product.get("color", ""),
        product.get("material", ""),
        product.get("size", ""),
        product.get("description", ""),
    ]
    return _normalize_match_text(" ".join(str(v or "") for v in values))


def _matches_profile_value(product_text: str, dimension: str, value: str) -> bool:
    return _contains_any(product_text, PRODUCT_MATCH_TABLES[dimension].get(value, []))


def _match_language(language: str | None) -> str:
    code = (language or "en").split("-")[0].lower()
    return code if code in PRODUCT_MATCH_SUPPORTED_LANGUAGES else "en"


def _match_label(dimension: str, value: str, language: str) -> str:
    labels = PRODUCT_MATCH_VALUE_LABELS.get(dimension, {}).get(value, {})
    return labels.get(language) or labels.get("en") or value


def _join_match_labels(labels: list[str], language: str) -> str:
    labels = [label for label in labels if label]
    if not labels:
        return ""
    if language == "en":
        return ", ".join(labels)
    if language == "es":
        return ", ".join(labels)
    if language == "fr":
        return ", ".join(labels)
    if language in {"ja", "ko"}:
        return "、".join(labels)
    return "、".join(labels)


def _constraint_phrase(profile: dict[str, set[str]], language: str, *, skip: tuple[str, str] | None = None) -> str:
    ordered_dimensions = ("brands", "styles", "colors", "materials", "spaces", "categories")
    labels: list[str] = []
    for dimension in ordered_dimensions:
        for value in sorted(profile.get(dimension) or []):
            if skip and skip == (dimension, value):
                continue
            label = _match_label(dimension, value, language)
            if label and label not in labels:
                labels.append(label)
    if language in {"en", "es", "fr"}:
        return " ".join(labels)
    return "".join(labels)


def _alternative_phrases(
    profile: dict[str, set[str]],
    unsatisfied: list[dict[str, str]],
    language: str,
) -> list[str]:
    phrases: list[str] = []
    for item in unsatisfied[:2]:
        dimension = item.get("dimension") or ""
        value = item.get("value") or ""
        phrase = _constraint_phrase(profile, language, skip=(dimension, value))
        if phrase and phrase not in phrases:
            phrases.append(phrase)
        category_phrase = _constraint_phrase({"categories": profile.get("categories", set())}, language)
        missing_label = _match_label(dimension, value, language)
        missing_phrase = f"{missing_label} {category_phrase}".strip() if language in {"en", "es", "fr"} else f"{missing_label}{category_phrase}"
        if missing_phrase and missing_phrase not in phrases:
            phrases.append(missing_phrase)
    return phrases[:2]


PRODUCT_MATCH_CONSTRAINT_TEMPLATES = {
    "zh": "暂时没有完全符合“{request}”的商品，我可以先为您推荐接近的{alternatives}。",
    "en": "We do not currently have an exact match for \"{request}\". I can first recommend close alternatives such as {alternatives}.",
    "ja": "「{request}」に完全一致する商品は現在見つかりません。まずは近い候補として{alternatives}をご提案します。",
    "ko": "현재 \"{request}\" 조건에 완전히 맞는 상품은 없습니다. 우선 가까운 대안인 {alternatives} 상품을 추천드릴 수 있습니다.",
    "es": "Por ahora no tenemos un producto que coincida exactamente con \"{request}\". Puedo recomendarle primero alternativas cercanas como {alternatives}.",
    "fr": "Nous n'avons pas actuellement de produit correspondant exactement à « {request} ». Je peux d'abord vous recommander des alternatives proches comme {alternatives}.",
}

PRODUCT_MATCH_CONSTRAINT_ADMIN_TEMPLATES = {
    "zh": "匹配提示：客户条件未完全满足，缺少：{missing}。",
    "en": "Match notice: the customer constraints are not fully satisfied. Missing: {missing}.",
    "ja": "マッチング通知：お客様の条件を完全には満たしていません。不足：{missing}。",
    "ko": "매칭 알림: 고객 조건이 완전히 충족되지 않았습니다. 부족: {missing}.",
    "es": "Aviso de coincidencia: las condiciones del cliente no se satisfacen por completo. Falta: {missing}.",
    "fr": "Alerte de correspondance : les critères client ne sont pas entièrement satisfaits. Manquant : {missing}.",
}


def build_product_constraint_notice(
    user_message: str,
    products: list[dict],
    language: str = "en",
) -> dict[str, Any]:
    """Return a localized notice when explicit product constraints are only partially satisfiable."""
    lang = _match_language(language)
    profile = _extract_product_query_profile(user_message)
    if not profile.get("categories"):
        return {"has_notice": False}

    category_pool = [
        product for product in products
        if any(_matches_profile_value(_product_match_text(product), "categories", value) for value in profile["categories"])
    ]
    if not category_pool:
        return {"has_notice": False}

    unsatisfied: list[dict[str, str]] = []
    for dimension in PRODUCT_MATCH_STRICT_DIMENSIONS:
        for value in sorted(profile.get(dimension) or []):
            matched = any(
                _matches_profile_value(_product_match_text(product), dimension, value)
                for product in category_pool
            )
            if not matched:
                unsatisfied.append({
                    "dimension": dimension,
                    "value": value,
                    "label": _match_label(dimension, value, lang),
                })

    if not unsatisfied:
        return {"has_notice": False}

    request = _constraint_phrase(profile, lang) or user_message.strip()
    alternatives = _alternative_phrases(profile, unsatisfied, lang)
    if not alternatives:
        alternatives = [_constraint_phrase({"categories": profile.get("categories", set())}, lang)]
    alternatives_text = _join_match_labels(alternatives, lang) or request
    missing_text = _join_match_labels([item["label"] for item in unsatisfied], lang)
    text = PRODUCT_MATCH_CONSTRAINT_TEMPLATES[lang].format(
        request=request,
        alternatives=alternatives_text,
    )
    admin_text = PRODUCT_MATCH_CONSTRAINT_ADMIN_TEMPLATES[lang].format(missing=missing_text)
    return {
        "has_notice": True,
        "language": lang,
        "text": text,
        "admin_text": admin_text,
        "missing": unsatisfied,
        "request": request,
        "alternatives": alternatives,
    }


def _score_product_candidate(
    product: dict[str, Any],
    profile: dict[str, set[str]],
    query_terms: list[str] | None = None,
) -> int:
    product_text = _product_match_text(product)
    has_constraints = any(profile.values())
    score = 0

    for dimension, values in profile.items():
        if not values:
            continue
        weight = PRODUCT_MATCH_WEIGHTS[dimension]
        matched = any(_matches_profile_value(product_text, dimension, value) for value in values)
        if matched:
            score += weight
        elif dimension == "categories":
            score -= weight
        else:
            score -= max(3, weight // 5)

    if product.get("image_paths"):
        score += 8
    if product.get("buy_url") or product.get("detail_url"):
        score += 4
    if product.get("space"):
        score += 2
    if product.get("style"):
        score += 2
    if query_terms:
        score += 60 if any(term in product_text for term in query_terms) else 0

    if not has_constraints:
        score += len(str(product.get("name") or "")) > 0
        score += 8 if product.get("image_paths") else 0
        score += 4 if product.get("buy_url") or product.get("detail_url") else 0
    return int(score)


def _local_product_candidates(
    user_message: str,
    products: list[dict],
    limit: int = PRODUCT_MATCH_CANDIDATE_LIMIT,
) -> list[tuple[dict, int]]:
    profile = _extract_product_query_profile(user_message)
    query_terms = _extract_product_query_terms(user_message)
    scored = [(product, _score_product_candidate(product, profile, query_terms)) for product in products]
    scored.sort(key=lambda item: (-item[1], int(item[0].get("id") or 0)))

    if any(profile.values()):
        positive = [item for item in scored if item[1] > 0]
        if len(positive) >= min(3, len(scored)):
            selected = positive[:limit]
            if len(selected) < limit:
                selected.extend([item for item in scored if item not in selected][: limit - len(selected)])
            return selected[:limit]
    return scored[:limit]


def _fallback_product_ids(candidates: list[tuple[dict, int]], count: int = 3) -> list[int]:
    ids: list[int] = []
    for product, _score in candidates:
        try:
            pid = int(product.get("id"))
        except (TypeError, ValueError):
            continue
        if pid not in ids:
            ids.append(pid)
        if len(ids) >= count:
            break
    return ids


def _protected_exact_product_ids(
    candidates: list[tuple[dict, int]],
    query_terms: list[str],
    count: int = 2,
) -> list[int]:
    if not candidates or not query_terms:
        return []
    top_score = candidates[0][1]
    ids: list[int] = []
    for product, score in candidates:
        if score < top_score - 5:
            break
        product_text = _product_match_text(product)
        if not any(term in product_text for term in query_terms):
            continue
        try:
            pid = int(product.get("id"))
        except (TypeError, ValueError):
            continue
        if pid not in ids:
            ids.append(pid)
        if len(ids) >= count:
            break
    return ids


def _parse_product_id_array(raw: str, valid_ids: set[int]) -> list[int]:
    match = re.search(r"\[[^\]]*\]", raw or "")
    if not match:
        return []
    try:
        ids = json.loads(match.group())
    except Exception:
        return []
    if not isinstance(ids, list):
        return []
    out: list[int] = []
    for item in ids:
        try:
            pid = int(float(item))
        except (TypeError, ValueError):
            continue
        if pid in valid_ids and pid not in out:
            out.append(pid)
    return out[:3]


async def ai_select_products(
    user_message: str,
    products: list[dict],
    conversation_memory: str = "",
) -> list[int]:
    """Select product recommendations with local recall, LLM rerank, and deterministic fallback."""
    if not products:
        return []
    candidates = _local_product_candidates(user_message, products)
    query_terms = _extract_product_query_terms(user_message)
    protected_ids = _protected_exact_product_ids(candidates, query_terms)
    fallback_ids = _fallback_product_ids(candidates)
    if not candidates:
        return fallback_ids

    memory_section = ""
    if conversation_memory.strip():
        memory_section = (
            "Same-conversation memory to respect when relevant:\n"
            f"{conversation_memory.strip()}\n\n"
        )
    catalog = "\n".join(
        f"ID:{p.get('id')} | score:{score} | 品牌:{p.get('brand', '')} | {p.get('name', '')} | 系列:{p.get('series', '')} | 空间:{p.get('space', '')} "
        f"| 风格:{p.get('style', '')} | 颜色:{p.get('color', '')} | 材质:{p.get('material', '')}"
        for p, score in candidates
    )
    valid_ids = {int(p["id"]) for p, _score in candidates if p.get("id") is not None}
    logger.info(
        "Product matching local recall: total=%d candidates=%d catalog_chars=%d fallback=%s",
        len(products),
        len(candidates),
        len(catalog),
        fallback_ids,
    )
    try:
        result = await asyncio.wait_for(
            _chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a furniture product matcher. The customer wants product recommendations.\n"
                            "Given the pre-filtered candidate catalog below, pick up to 3 product IDs that BEST match the request.\n"
                            "RULES:\n"
                            "- Match by category, brand, style, room/space, color, material, series, or name.\n"
                            "- Prefer the candidate score when quality is otherwise similar, but override it when the customer request clearly says so.\n"
                            "- If same-conversation memory includes explicit preferences, use them when the latest request is underspecified.\n"
                            "- If the latest request clearly overrides previous preferences, follow the latest request.\n"
                            "- Return a JSON array of numeric IDs, e.g. [12, 45, 78]\n"
                            "- If nothing matches, return []\n"
                            "- Output ONLY the JSON array, no explanation.\n\n"
                            f"{memory_section}"
                            f"CANDIDATE CATALOG:\n{catalog}"
                        ),
                    },
                    {"role": "user", "content": user_message},
                ],
                max_tokens=100,
                temperature=0,
                disable_thinking=True,
            ),
            timeout=PRODUCT_MATCH_LLM_TIMEOUT_SECONDS,
        )
        raw = result.strip()
        logger.info(f"AI product selection raw response: {raw[:200]}")
        out = _parse_product_id_array(raw, valid_ids)
        for pid in reversed(protected_ids):
            if pid in out:
                out.remove(pid)
            out.insert(0, pid)
        for pid in fallback_ids:
            if pid not in out:
                out.append(pid)
            if len(out) >= 3:
                break
        return out[:3] or fallback_ids
    except asyncio.TimeoutError:
        logger.warning(
            "Product AI selection timed out after %ss; falling back to local ranking ids=%s",
            PRODUCT_MATCH_LLM_TIMEOUT_SECONDS,
            fallback_ids,
        )
        return fallback_ids
    except Exception as e:
        logger.error(f"Product AI selection failed; falling back to local ranking: {e}")
        return fallback_ids


LANGUAGE_NAMES = {
    "zh": "中文", "en": "English", "ja": "日本語", "ko": "한국어",
    "es": "Español", "fr": "Français", "de": "Deutsch", "ar": "العربية",
    "ru": "Русский", "pt": "Português", "it": "Italiano", "th": "ภาษาไทย",
    "vi": "Tiếng Việt", "id": "Bahasa Indonesia", "ms": "Bahasa Melayu",
    "tr": "Türkçe", "nl": "Nederlands", "pl": "Polski", "hi": "हिन्दी",
}


async def generate_response(
    user_message: str,
    context: str,
    language: str,
    chat_history: list[dict] | None = None,
    file_info: str = "",
    conversation_memory: str = "",
) -> str:
    lang_name = LANGUAGE_NAMES.get(language, "English")

    file_section = ""
    if file_info:
        file_section = (
            f"\n\nAvailable files that may be relevant:\n{file_info}\n"
            f"If a file is relevant to the customer's question, mention it in your response "
            f"and let them know you will send it."
        )
    memory_section = ""
    if conversation_memory.strip():
        memory_section = (
            f"\n\nSame-conversation memory (use only when relevant to the current question):\n"
            f"{conversation_memory.strip()}\n"
            f"If the latest user message contradicts this memory, prefer the latest user message."
        )

    has_kb = bool(context and context.strip())
    if has_kb:
        system_prompt = (
            f"You are a professional and friendly customer service agent. "
            f"You MUST respond in {lang_name} ({language}). "
            f"Use the following retrieved knowledge base excerpts as the primary source of facts. "
            f"Prefer citing or paraphrasing them when they apply. "
            f"If the user's question matches FAQ-style or 'common questions' (常见问题) content in the excerpts, "
            f"you MUST answer using the answer text given there—paraphrase only for clarity and language, "
            f"do not substitute different facts or generic guesses. "
            f"If the excerpts do not cover the question, say so briefly and offer human support.\n\n"
            f"Knowledge Base Context:\n{context}\n"
            f"{memory_section}"
            f"{file_section}\n\n"
            f"Rules:\n"
            f"1. Always respond in {lang_name}\n"
            f"2. Be professional, helpful and concise\n"
            f"3. If unsure, suggest contacting human support\n"
            f"4. Do not invent product/policy details that contradict the context above\n"
            f"5. FAQ/common-question matches: follow the knowledge base answer as the authoritative response"
        )
    else:
        system_prompt = (
            f"You are a professional and friendly customer service agent. "
            f"You MUST respond in {lang_name} ({language}). "
            f"No knowledge base snippets were retrieved for this question; answer helpfully from "
            f"general customer-service practice, and suggest contacting a human agent for specifics.\n"
            f"{memory_section}"
            f"{file_section}\n\n"
            f"Rules:\n"
            f"1. Always respond in {lang_name}\n"
            f"2. Be professional, helpful and concise\n"
            f"3. If unsure, suggest contacting human support"
        )

    messages = [{"role": "system", "content": system_prompt}]
    if chat_history:
        for msg in chat_history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        return await _chat_completion(messages=messages)
    except Exception as e:
        logger.error(f"Response generation failed: {e}")
        error_messages = {
            "zh": "抱歉，系统暂时出现问题，请稍后再试或联系人工客服。",
            "en": "Sorry, the system is temporarily unavailable. Please try again later or contact human support.",
            "ja": "申し訳ございません。システムに一時的な問題が発生しました。後ほどお試しください。",
        }
        return error_messages.get(language, error_messages["en"])


_OUTPUT_FORMAT_CONTRACT = (
    "OUTPUT FORMAT (mandatory, no text before TITLE):\n"
    "LINE 1: TITLE: <short document title ONLY — one line, max ~40 characters, plain language "
    "such as the deal type, e.g. 产品销售合同 / Service Agreement / 采购订单. No quotes, no markdown, no numbering.\n"
    "LINE 2: exactly three dashes: ---\n"
    "LINE 3 onward: the full contract body (sections, clauses, signature blocks as appropriate).\n"
    "Do not repeat the title inside the body as a duplicate heading unless the template requires it."
)


async def generate_contract(
    chat_history: list[dict],
    customer_name: str,
    language: str = "en",
    template_content: str | None = None,
) -> str:
    lang_name = LANGUAGE_NAMES.get(language, "English")

    conversation_text = "\n".join(
        f"{'Customer' if m['role'] == 'user' else 'Agent'}: {m['content']}"
        for m in chat_history
    )

    if template_content and template_content.strip():
        prompt = (
            f"You are given a CONTRACT TEMPLATE (plain text from a Word document). "
            f"Fill and revise it using the conversation: names, amounts, dates, products, and terms "
            f"that appear or are clearly implied. Keep the template's section order and headings where sensible.\n\n"
            f"Customer display name: {customer_name}\n\n"
            f"--- TEMPLATE ---\n{template_content}\n--- END TEMPLATE ---\n\n"
            f"--- CONVERSATION ---\n{conversation_text}\n--- END CONVERSATION ---\n\n"
            f"{_OUTPUT_FORMAT_CONTRACT}\n"
            f"The contract body after --- must be entirely in {lang_name}."
        )
        system_msg = (
            f"You are a precise contract drafting assistant. "
            f"Prefer clear, standard wording; avoid unnecessary legalese. "
            f"Follow the mandatory TITLE/--- format. Write contract body in {lang_name}."
        )
    else:
        prompt = (
            f"Draft a practical contract or agreement in {lang_name} from this customer service chat. "
            f"Use only what the conversation supports; mark gaps briefly if something critical is missing.\n\n"
            f"Customer: {customer_name}\n\n"
            f"--- CONVERSATION ---\n{conversation_text}\n--- END CONVERSATION ---\n\n"
            f"Include as applicable: parties, scope, deliverables, price/payment, timeline, "
            f"termination, governing law only if discussed, and signature lines.\n\n"
            f"{_OUTPUT_FORMAT_CONTRACT}"
        )
        system_msg = (
            f"You are a professional contract drafting assistant: clear structure, plain where possible, "
            f"accurate to the chat. You MUST use the TITLE: / --- / body format. Body in {lang_name}."
        )

    try:
        return await _chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            max_tokens=4000,
            temperature=0.3,
        )
    except Exception as e:
        logger.error(f"Contract generation failed: {e}")
        return f"Error generating contract: {str(e)}"


async def test_llm_connection(provider: str, api_key: str, base_url: str, model: str) -> dict:
    """Test the LLM connection with given parameters. Returns {ok, message}."""
    try:
        if provider == "anthropic":
            client = AsyncAnthropic(api_key=api_key)
            resp = await client.messages.create(
                model=model, max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}],
            )
            return {"ok": True, "message": f"Connected. Response: {resp.content[0].text[:50]}"}
        else:
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            resp = await client.chat.completions.create(
                model=model, max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}],
            )
            return {"ok": True, "message": f"Connected. Response: {resp.choices[0].message.content[:50]}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


async def test_embedding_connection(api_key: str, base_url: str, model: str) -> dict:
    """Test the embedding model connection. Returns {ok, message}."""
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resolved_model = _resolve_embedding_model(base_url, model)
        resp = await client.embeddings.create(model=resolved_model, input="hello")
        dim = len(resp.data[0].embedding)
        return {"ok": True, "message": f"Embedding OK — model: {resolved_model}, dimension: {dim}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


async def test_image_connection(api_key: str, base_url: str, model: str, size: str, quality: str) -> dict:
    """Test the image generation model. Returns {ok, message}."""
    import httpx, asyncio
    from urllib.parse import urlparse

    if model.startswith("kling/"):
        return await _test_dashscope_kling(api_key, base_url, model, size)

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.images.generate(
            model=model,
            prompt="A single white dot on a black background",
            n=1,
            size=size,
            quality=quality,
        )
        url_or_b64 = resp.data[0].url or (resp.data[0].b64_json or "")[:30]
        return {"ok": True, "message": f"Image generation OK — result: {url_or_b64[:80]}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


async def _test_dashscope_kling(api_key: str, base_url: str, model: str, size: str) -> dict:
    """Test DashScope Kling image generation with a minimal request."""
    import httpx, asyncio
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base_url.rstrip("/")

    create_url = f"{root}/api/v1/services/aigc/image-generation/generation"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    def _aspect_ratio(s: str) -> str:
        try:
            w, h = s.lower().split("x", 1)
            return "1:1" if abs(int(w) - int(h)) < 50 else ("16:9" if int(w) > int(h) else "9:16")
        except Exception:
            return "1:1"

    payload = {
        "model": model,
        "input": {
            "messages": [{"role": "user", "content": [{"text": "A single white dot on a black background"}]}]
        },
        "parameters": {"n": 1, "aspect_ratio": _aspect_ratio(size), "resolution": "1k", "watermark": False},
    }

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            create_resp = await client.post(create_url, headers=headers, json=payload)
            create_resp.raise_for_status()
            created = create_resp.json()
            task_id = ((created.get("output") or {}).get("task_id"))
            if not task_id:
                return {"ok": False, "message": created.get("message") or "Task creation failed — no task_id returned"}

            query_url = f"{root}/api/v1/tasks/{task_id}"
            for _ in range(36):
                await asyncio.sleep(5)
                poll_resp = await client.get(query_url, headers={"Authorization": f"Bearer {api_key}"})
                poll_resp.raise_for_status()
                output = (poll_resp.json().get("output") or {})
                status = output.get("task_status")
                if status == "SUCCEEDED":
                    contents = ((output.get("choices") or [{}])[0].get("message") or {}).get("content") or []
                    urls = [item.get("image") for item in contents if item.get("image")]
                    return {"ok": True, "message": f"Kling image generation OK — got {len(urls)} image(s)"}
                if status == "FAILED":
                    return {"ok": False, "message": poll_resp.json().get("message") or "Kling task failed"}
            return {"ok": False, "message": "Kling image generation timed out (3 min)"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


async def translate_text(text: str, target_language: str) -> str | None:
    """Translate text into the target language. Returns None on failure."""
    lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a professional translator. Translate the following text into {lang_name}. "
                        f"Return ONLY the translated text, nothing else. "
                        f"Keep the original meaning, tone and formatting."
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=2000,
            temperature=0.3,
        )
        return result.strip()
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return None
