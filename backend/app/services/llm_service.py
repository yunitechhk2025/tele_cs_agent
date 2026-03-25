import json
import logging
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
            db_settings = {r.key: r.value for r in list(rows) + list(rows2)}

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


async def _chat_completion(messages: list[dict], max_tokens: int | None = None, temperature: float | None = None) -> str:
    """Unified chat completion that routes to the correct provider."""
    cfg = await get_llm_settings()
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
    client = _build_embedding_client(cfg)
    model = cfg.get("embedding_model", "text-embedding-3-small")
    try:
        response = await client.embeddings.create(model=model, input=text)
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return []


# ─── Public API (used by bot and other services) ─────────────────────────────

async def detect_language(text: str) -> str:
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a language detector. Return ONLY the ISO 639-1 language code "
                        "(e.g., 'en', 'zh', 'ja', 'ko', 'es', 'fr', 'de', 'ar', 'ru', 'pt'). "
                        "Nothing else."
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


def might_want_product_image(text: str) -> bool:
    """Heuristic: user is asking for product photos / pictures (not necessarily pricing)."""
    if not text or len(text.strip()) < 2:
        return False
    t = text.lower()
    for kw in ("商品图", "产品图", "实物图", "发个图", "发图", "有没有图", "有图吗", "发一下图", "发张图"):
        if kw in text:
            return True
    if "图" in text and any(w in text for w in ("椅", "商品", "产品", "货", "款", "样子", "沙发", "桌", "床")):
        return True
    for kw in ("product image", "product photo", "picture of", "photo of", "image of", "send me a pic", "send a photo"):
        if kw in t:
            return True
    if any(k in t for k in (" picture", " photo", " image", " pic ")) and any(
        w in t for w in ("product", "chair", "item", "goods", "catalog")
    ):
        return True
    return False


async def match_product_image_files(user_message: str, available_files: list[dict]) -> list[int]:
    """Pick at most one file from the library that best matches a product-image request. Prefer image/* files."""
    if not available_files:
        return []
    image_files = [f for f in available_files if (f.get("mime_type") or "").lower().startswith("image/")]
    catalog = image_files if image_files else available_files
    file_list = "\n".join(
        f"- ID:{f['id']} | {f['name']} | {f['description']} | tags: {f['tags']} | mime: {f.get('mime_type') or 'unknown'}"
        for f in catalog
    )
    try:
        result = await _chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "The customer is asking for product photos, images, or pictures "
                        "(e.g. chair photo, 椅子图片, product image). "
                        "Match their request to exactly ONE best file ID from the catalog below. "
                        "Prefer images (image/* mime) when the user wants a picture. "
                        "Return a JSON array with a single id, e.g. [3], or [] if nothing fits.\n"
                        "Return ONLY the JSON array, nothing else.\n\n"
                        f"File catalog:\n{file_list}"
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            max_tokens=40,
            temperature=0,
        )
        raw = result.strip()
        if "[" not in raw:
            return []
        ids = json.loads(raw)
        if not isinstance(ids, list):
            return []
        out: list[int] = []
        for x in ids:
            try:
                out.append(int(float(x)))
            except (TypeError, ValueError):
                continue
        return out[:1]
    except Exception as e:
        logger.error(f"Product image match failed: {e}")
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
