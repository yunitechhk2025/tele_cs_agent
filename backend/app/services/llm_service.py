import json
import logging
import re
import os
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


async def _chat_completion(messages: list[dict], max_tokens: int | None = None, temperature: float | None = None) -> str:
    """Unified chat completion that routes to the correct provider."""
    cfg = await get_llm_settings()
    if _llm_disabled(cfg):
        return _mock_chat_completion(messages)
    provider = cfg.get("llm_provider", "openai").lower()
    model = cfg.get("llm_model", "gpt-4o")
    temp = temperature if temperature is not None else float(cfg.get("llm_temperature", "0.7"))
    mt = max_tokens or int(cfg.get("llm_max_tokens", "1000"))

    if provider == "anthropic":
        return await _anthropic_chat(cfg, messages, model, mt, temp)
    else:
        return await _openai_chat(cfg, messages, model, mt, temp)


async def _openai_chat(cfg: dict, messages: list[dict], model: str, max_tokens: int, temperature: float) -> str:
    client = _build_openai_client(cfg)
    response = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=temperature,
    )
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
    if _llm_disabled(cfg):
        return _mock_embedding(text)
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
    """Fast character-based language detection as fallback.

    重要：日文句子里几乎一定包含 CJK 统一表意文字（汉字），例如「商品について
    教えてください」。如果先判 `[\u4e00-\u9fff]` 会把所有日语都错判成 zh。
    所以先看**只属于日语**的平假名 / 片假名（U+3040-U+30FF），命中即判 ja；
    韩文谚文同理优先于汉字检测。剩下纯汉字才算中文。"""
    import re
    # 韩文专属字符 → ko
    if re.search(r'[\uac00-\ud7af]', text):
        return "ko"
    # 平假名 / 片假名 / 半角片假名 → ja（即使句中混有汉字）
    if re.search(r'[\u3040-\u30ff\uff66-\uff9f]', text):
        return "ja"
    # 走到这里说明既无谚文也无假名，剩下的 CJK 汉字归为中文
    if re.search(r'[\u4e00-\u9fff]', text):
        return "zh"
    if re.search(r'[\u0600-\u06ff]', text):
        return "ar"
    if re.search(r'[\u0400-\u04ff]', text):
        return "ru"
    return None


def _llm_disabled(cfg: dict[str, str]) -> bool:
    """When no API key is configured, run in mock mode so local dev can start."""
    flag = (os.getenv("LLM_DISABLED") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    # Auto-disable if no key configured
    return not (cfg.get("llm_api_key") or "").strip()


def _mock_embedding(text: str, dim: int = 64) -> list[float]:
    """Deterministic cheap embedding for local dev (no network / no keys)."""
    import hashlib

    raw = (text or "").encode("utf-8", errors="ignore")
    digest = hashlib.sha256(raw).digest()
    out: list[float] = []
    # Expand digest deterministically to dim floats in [-1, 1]
    while len(out) < dim:
        for b in digest:
            out.append((b / 127.5) - 1.0)
            if len(out) >= dim:
                break
        digest = hashlib.sha256(digest).digest()
    return out


def _mock_chat_completion(messages: list[dict]) -> str:
    """Return minimal well-formed outputs for common internal prompts."""
    system = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    user = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
    s = (system or "").lower()
    u = (user or "").strip()

    # JSON boolean classifiers
    if 'return json: {"is_quote": true}' in s:
        return '{"is_quote": false}'
    if 'return json: {"is_product_rec": true}' in s:
        return '{"is_product_rec": false}'
    if 'return json: {"is_confirmed": true}' in s:
        return '{"is_confirmed": false}'

    # File matcher expects JSON array
    if "return only the json array" in s and "file catalog" in s:
        return "[]"

    # Intent router expects compact JSON object
    if "intent router" in s and "primary_intent" in s and "secondary_intents" in s:
        return (
            '{"primary_intent":"general_question","secondary_intents":[],"confidence":0.2,'
            '"slots":{"target_product_id":null,"scene_name":"","style_hint":"","file_ids":[]},'
            '"needs_human":false,"clarification_question":"","reason":"mock-llm-disabled"}'
        )

    # Language detector: return a code
    if "you are a language detector" in s and "iso 639-1" in s:
        return "en"

    # Contract generator: return TITLE/---/body
    if "output format (mandatory" in s and "title:" in s:
        return "TITLE: Service Agreement\n---\nThis is a mock contract generated in local dev (LLM disabled)."

    # Generic: echo a short helpful reply without pretending it's AI-generated knowledge
    return "（本地开发模式：LLM 未配置，已返回占位回复。请在环境变量中配置 LLM Key 后启用真实模型。）"


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
    # 把最近 6 轮历史拼进 prompt，让路由器能解析"这个/它/那款/价格呢"等省略式追问。
    # 使用对话格式而非 system 上下文，便于模型用最自然的指代消解能力。
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


async def ai_select_products(user_message: str, products: list[dict]) -> list[int]:
    """Use AI to select up to 3 best-matching product IDs from the catalog."""
    import re
    if not products:
        return []
    catalog = "\n".join(
        f"ID:{p['id']} | 品牌:{p.get('brand', '')} | {p['name']} | 系列:{p['series']} | 空间:{p['space']} "
        f"| 风格:{p['style']} | 颜色:{p['color']}"
        for p in products
    )
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a furniture product matcher. The customer wants product recommendations.\n"
                        "Given the catalog below, pick up to 3 product IDs that BEST match the request.\n"
                        "RULES:\n"
                        "- Match by brand, style, space, color, series, or name.\n"
                        "- Return a JSON array of numeric IDs, e.g. [12, 45, 78]\n"
                        "- If nothing matches, return []\n"
                        "- Output ONLY the JSON array, no explanation.\n\n"
                        f"CATALOG:\n{catalog}"
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            max_tokens=100,
            temperature=0,
        )
        raw = result.strip()
        logger.info(f"AI product selection raw response: {raw[:200]}")
        m = re.search(r'\[[\d\s,]*\]', raw)
        if not m:
            return []
        ids = json.loads(m.group())
        if not isinstance(ids, list):
            return []
        valid_ids = {p['id'] for p in products}
        out: list[int] = []
        for x in ids:
            try:
                pid = int(float(x))
                if pid in valid_ids:
                    out.append(pid)
            except (TypeError, ValueError):
                continue
        return out[:3]
    except Exception as e:
        logger.error(f"Product AI selection failed: {e}")
        return []


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
) -> str:
    lang_name = LANGUAGE_NAMES.get(language, "English")

    file_section = ""
    if file_info:
        file_section = (
            f"\n\nAvailable files that may be relevant:\n{file_info}\n"
            f"If a file is relevant to the customer's question, mention it in your response "
            f"and let them know you will send it."
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
