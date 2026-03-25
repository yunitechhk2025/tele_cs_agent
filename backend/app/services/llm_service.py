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
        f"- ID:{f['id']} | {f['name']} | {f['description']} | tags: {f['tags']}"
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

    system_prompt = (
        f"You are a professional and friendly customer service agent. "
        f"You MUST respond in {lang_name} ({language}). "
        f"Use the following knowledge base context to answer the customer's question. "
        f"If the context doesn't contain relevant information, politely let the customer know "
        f"and offer to connect them with a human agent.\n\n"
        f"Knowledge Base Context:\n{context}\n"
        f"{file_section}\n\n"
        f"Rules:\n"
        f"1. Always respond in {lang_name}\n"
        f"2. Be professional, helpful and concise\n"
        f"3. If unsure, suggest contacting human support\n"
        f"4. Do not make up information not in the context"
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
            f"You are given a CONTRACT TEMPLATE (plain text extracted from a Word document). "
            f"Revise and fill it using the customer service conversation below. "
            f"Replace placeholders, fill in names, amounts, dates, product details, and terms "
            f"that appear or are implied in the chat. Keep the template's overall structure "
            f"and section order. Output the complete contract in {lang_name} only, as plain text.\n\n"
            f"Customer display name: {customer_name}\n\n"
            f"--- TEMPLATE ---\n{template_content}\n--- END TEMPLATE ---\n\n"
            f"--- CONVERSATION ---\n{conversation_text}\n--- END CONVERSATION ---"
        )
        system_msg = (
            f"You are a professional contract drafting assistant. "
            f"Follow the template structure; adapt content from the conversation. Write in {lang_name}."
        )
    else:
        prompt = (
            f"Based on the following customer service conversation, generate a professional "
            f"contract/agreement draft in {lang_name}. Extract key terms, requirements, "
            f"and any agreed-upon details from the conversation.\n\n"
            f"Customer Name: {customer_name}\n\n"
            f"Conversation:\n{conversation_text}\n\n"
            f"Generate a complete contract draft with:\n"
            f"1. Title\n2. Parties involved\n3. Scope of services/products\n"
            f"4. Terms and conditions\n5. Payment terms (if discussed)\n"
            f"6. Timeline (if discussed)\n7. Signature blocks\n\n"
            f"Format the contract professionally in {lang_name}."
        )
        system_msg = f"You are a professional contract drafting assistant. Write in {lang_name}."

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
