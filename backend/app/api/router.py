import asyncio
import json
import logging
import os
import shutil
import uuid
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db, AsyncSessionLocal
from app.models import (
    Conversation, Message, KnowledgeEntry, Contract, ContractTemplate, FileEntry, TelegramBot,
    ConversationStatus, MessageRole, ProductEntry, ProductImage, SceneGenerationImage, SceneGenerationRecord,
)
from app.schemas import (
    LoginRequest, TokenResponse, ConversationSchema, ConversationDetailSchema,
    ReplyRequest, KnowledgeEntrySchema, KnowledgeCreateRequest,
    ContractSchema, ContractUpdateRequest, ContractGenerateRequest, SendContractRequest, DashboardStats,
    LLMSettingsSchema, LLMSettingsUpdateRequest,
    FileEntrySchema, FileEntryUpdateRequest,
    TelegramBotSchema, TelegramBotCreateRequest, TelegramBotUpdateRequest,
    ContractTemplateSchema,
    ProductEntrySchema, ProductEntryListSchema, ProductImageSchema, SceneGenerationRequest, SceneGenerationRecordSchema,
    SceneLibraryItemSchema, SceneGeneratorRequest,
)
from app.services.rag_service import (
    add_to_knowledge_base, remove_from_knowledge_base,
    add_file_to_index, remove_file_from_index,
)
from app.services.contract_service import (
    create_contract_from_conversation,
    export_contract_to_docx_bytes,
    extract_docx_text_from_bytes,
    looks_like_ooxml_docx,
    sanitize_contract_filename,
)
from app.services.llm_service import (
    get_llm_settings, save_llm_settings, invalidate_llm_cache,
    test_llm_connection, test_embedding_connection, test_image_connection,
    LLM_SETTING_KEYS, translate_text, detect_language,
)
from app.services.scene_service import generate_scene_images, build_scene_record_response, start_scene_generation
from app.services import bot_manager

logger = logging.getLogger(__name__)
settings = get_settings()
security = HTTPBearer()

router = APIRouter(prefix="/api")


# ─── Auth ────────────────────────────────────────────────────────────────────

def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    try:
        payload = jwt.decode(
            credentials.credentials, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    if req.username != settings.ADMIN_USERNAME or req.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(req.username)
    return TokenResponse(access_token=token)


# ─── Dashboard ───────────────────────────────────────────────────────────────

@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    total_conv = await db.scalar(select(func.count(Conversation.id)))
    active_conv = await db.scalar(
        select(func.count(Conversation.id)).where(Conversation.status == ConversationStatus.ACTIVE)
    )
    pending = await db.scalar(
        select(func.count(Conversation.id)).where(Conversation.status == ConversationStatus.PENDING_HUMAN)
    )
    total_msg = await db.scalar(select(func.count(Message.id)))
    total_kb = await db.scalar(select(func.count(KnowledgeEntry.id)))
    total_contracts = await db.scalar(select(func.count(Contract.id)))
    total_files = await db.scalar(select(func.count(FileEntry.id)))
    total_bots = await db.scalar(select(func.count(TelegramBot.id)))
    active_bots_count = await db.scalar(
        select(func.count(TelegramBot.id)).where(TelegramBot.is_active == True)
    )

    recent = await db.execute(
        select(Conversation).order_by(desc(Conversation.updated_at)).limit(10)
    )

    return DashboardStats(
        total_conversations=total_conv or 0,
        active_conversations=active_conv or 0,
        pending_human=pending or 0,
        total_messages=total_msg or 0,
        total_knowledge_entries=total_kb or 0,
        total_contracts=total_contracts or 0,
        total_files=total_files or 0,
        total_bots=total_bots or 0,
        active_bots=active_bots_count or 0,
        recent_conversations=[
            ConversationSchema.model_validate(c) for c in recent.scalars().all()
        ],
    )


# ─── Conversations ───────────────────────────────────────────────────────────

@router.get("/conversations", response_model=list[ConversationSchema])
async def list_conversations(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = 0, limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    query = select(Conversation).order_by(desc(Conversation.updated_at))
    if status:
        query = query.where(Conversation.status == status)
    if search:
        query = query.where(
            (Conversation.username.ilike(f"%{search}%"))
            | (Conversation.first_name.ilike(f"%{search}%"))
            | (Conversation.last_name.ilike(f"%{search}%"))
        )
    result = await db.execute(query.offset(skip).limit(limit))
    return [ConversationSchema.model_validate(c) for c in result.scalars().all()]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailSchema)
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetailSchema.model_validate(conversation)


@router.post("/conversations/{conversation_id}/reply")
async def reply_to_conversation(
    conversation_id: int, req: ReplyRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    conversation = await db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    message = Message(conversation_id=conversation_id, role=MessageRole.HUMAN_AGENT, content=req.content)
    db.add(message)
    conversation.status = ConversationStatus.ACTIVE
    reply_target_lang = conversation.quote_language or conversation.language or "en"
    conversation.quote_language = None
    await db.commit()

    bot_instance = None
    if conversation.bot_id:
        bot_instance = bot_manager.get_bot_instance(conversation.bot_id)
    if not bot_instance:
        bot_instance = bot_manager.get_any_bot_instance()

    if bot_instance and conversation.telegram_chat_id:
        chat_id = int(conversation.telegram_chat_id)
        try:
            await bot_instance.send_message(chat_id=chat_id, text=req.content)
        except Exception as e:
            logger.error(f"Failed to send reply via Telegram: {e}")
            raise HTTPException(status_code=500, detail="Failed to send message via Telegram")

        agent_lang = await detect_language(req.content)
        logger.info(
            f"Reply translation check: conv={conversation_id}, "
            f"target={reply_target_lang}, agent_lang={agent_lang}"
        )
        if agent_lang != reply_target_lang:
            asyncio.create_task(
                _send_translation(bot_instance, chat_id, conversation_id, req.content, reply_target_lang)
            )

    return {"status": "sent"}


async def _send_translation(bot_instance, chat_id: int, conversation_id: int, text: str, target_lang: str):
    """Translate the agent reply and send as a follow-up message."""
    try:
        translated = await translate_text(text, target_lang)
        if not translated:
            return

        from app.services.llm_service import LANGUAGE_NAMES
        lang_label = LANGUAGE_NAMES.get(target_lang, target_lang)
        translated_msg = f"[{lang_label}]\n{translated}"

        await bot_instance.send_message(chat_id=chat_id, text=translated_msg)

        async with AsyncSessionLocal() as db:
            msg = Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=translated_msg,
                language=target_lang,
            )
            db.add(msg)
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to send translation for conversation {conversation_id}: {e}", exc_info=True)


@router.post("/conversations/{conversation_id}/send-contract")
async def send_contract_to_customer(
    conversation_id: int,
    req: SendContractRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    conversation = await db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    contract = await db.get(Contract, req.contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.conversation_id != conversation_id:
        raise HTTPException(status_code=400, detail="Contract does not belong to this conversation")

    bot_instance = None
    if conversation.bot_id:
        bot_instance = bot_manager.get_bot_instance(conversation.bot_id)
    if not bot_instance:
        bot_instance = bot_manager.get_any_bot_instance()

    if not bot_instance or not conversation.telegram_chat_id:
        raise HTTPException(status_code=503, detail="Telegram bot not available for this conversation")

    chat_id = int(conversation.telegram_chat_id)
    try:
        docx_bytes = export_contract_to_docx_bytes(contract.title, contract.content)
        fname = f"{sanitize_contract_filename(contract.title)}.docx"
        bio = BytesIO(docx_bytes)
        bio.seek(0)
        cap = f"📄 {contract.title}"[:1024]
        await bot_instance.send_document(
            chat_id=chat_id,
            document=bio,
            filename=fname,
            caption=cap,
        )
    except Exception as e:
        logger.error(f"Failed to send contract as Word via Telegram: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="发送合同 Word 文件失败，请稍后重试") from e

    message = Message(
        conversation_id=conversation_id,
        role=MessageRole.HUMAN_AGENT,
        content=f"[已发送合同 Word] {contract.title}",
    )
    db.add(message)
    contract.status = "sent"
    await db.commit()

    return {"status": "sent", "contract_id": contract.id}


@router.post("/conversations/{conversation_id}/close")
async def close_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    conversation = await db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation.status = ConversationStatus.CLOSED
    await db.commit()
    return {"status": "closed"}


# ─── Knowledge Base ──────────────────────────────────────────────────────────

@router.get("/knowledge", response_model=list[KnowledgeEntrySchema])
async def list_knowledge(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = 0, limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    query = select(KnowledgeEntry).order_by(desc(KnowledgeEntry.created_at))
    if category:
        query = query.where(KnowledgeEntry.category == category)
    if search:
        query = query.where(
            (KnowledgeEntry.title.ilike(f"%{search}%"))
            | (KnowledgeEntry.content.ilike(f"%{search}%"))
        )
    result = await db.execute(query.offset(skip).limit(limit))
    return [KnowledgeEntrySchema.model_validate(e) for e in result.scalars().all()]


@router.post("/knowledge", response_model=KnowledgeEntrySchema)
async def create_knowledge(
    req: KnowledgeCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    entry = KnowledgeEntry(title=req.title, content=req.content, source=req.source, category=req.category)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    ok = await add_to_knowledge_base(entry.id, entry.title, entry.content, entry.category)
    if not ok:
        logger.error(
            "Knowledge entry %s saved to DB but vector index failed (check embedding API / keys)",
            entry.id,
        )
    return KnowledgeEntrySchema.model_validate(entry)


@router.delete("/knowledge/{entry_id}")
async def delete_knowledge(entry_id: int, db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    entry = await db.get(KnowledgeEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    await remove_from_knowledge_base(entry_id)
    await db.delete(entry)
    await db.commit()
    return {"status": "deleted"}


@router.post("/knowledge/reindex")
async def reindex_knowledge_base(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Rebuild Chroma vectors from all knowledge_entries (after persistence/embedding fixes)."""
    result = await db.execute(select(KnowledgeEntry))
    rows = result.scalars().all()
    ok, fail = 0, 0
    for e in rows:
        if await add_to_knowledge_base(e.id, e.title, e.content, e.category):
            ok += 1
        else:
            fail += 1
    return {"status": "ok", "indexed": ok, "failed_embedding": fail, "total": len(rows)}


def _knowledge_text_from_upload(filename: str | None, content: bytes) -> str:
    name = (filename or "").lower().strip()
    treat_as_docx = name.endswith(".docx") or looks_like_ooxml_docx(content)
    if treat_as_docx:
        try:
            return extract_docx_text_from_bytes(content)
        except Exception as e:
            logger.warning("Failed to parse .docx for knowledge upload: %s", e)
            raise HTTPException(status_code=400, detail="无法解析 Word 文档，请确认是否为有效的 .docx 文件") from e
    if name.endswith((".txt", ".md", ".csv")):
        return content.decode("utf-8", errors="ignore")
    if name.endswith(".doc"):
        raise HTTPException(
            status_code=400,
            detail="不支持旧版 Word（.doc），请在 Word 中「另存为」.docx 后再上传",
        )
    # 无扩展名或非常见名：按纯文本兜底（兼容旧行为）；若实为 .docx 已由 looks_like_ooxml_docx 走上一分支
    if not name or not os.path.splitext(name)[1]:
        return content.decode("utf-8", errors="ignore")
    raise HTTPException(
        status_code=400,
        detail="不支持的文件类型，请上传 .txt、.md、.csv 或 .docx（不支持旧版 .doc）",
    )


@router.post("/knowledge/upload")
async def upload_knowledge_file(
    file: UploadFile = File(...),
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    content = await file.read()
    text = _knowledge_text_from_upload(file.filename, content)
    if not text.strip():
        raise HTTPException(status_code=400, detail="文件内容为空或无法提取文本")
    chunks = _split_text_into_chunks(text, max_chunk_size=1500)
    entries = []
    for i, chunk in enumerate(chunks):
        title = f"{file.filename} - Part {i + 1}" if len(chunks) > 1 else file.filename
        entry = KnowledgeEntry(title=title, content=chunk, source=file.filename, category=category or "uploaded")
        db.add(entry)
        await db.flush()
        ok = await add_to_knowledge_base(entry.id, entry.title, entry.content, entry.category)
        if not ok:
            logger.error(
                "Knowledge chunk entry_id=%s failed to index (embedding API); entry exists in DB only",
                entry.id,
            )
        entries.append(entry)
    await db.commit()
    return {"status": "uploaded", "chunks_created": len(entries)}


def _split_text_into_chunks(text: str, max_chunk_size: int = 1500) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chunk_size and current:
            chunks.append(current.strip())
            current = para
        else:
            current += "\n\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


# ─── Contracts ───────────────────────────────────────────────────────────────

@router.get("/contracts", response_model=list[ContractSchema])
async def list_contracts(
    status: Optional[str] = Query(None),
    conversation_id: Optional[int] = Query(None),
    skip: int = 0, limit: int = 50,
    db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user),
):
    query = select(Contract).order_by(desc(Contract.created_at))
    if status:
        query = query.where(Contract.status == status)
    if conversation_id is not None:
        query = query.where(Contract.conversation_id == conversation_id)
    result = await db.execute(query.offset(skip).limit(limit))
    return [ContractSchema.model_validate(c) for c in result.scalars().all()]


@router.get("/contracts/{contract_id}", response_model=ContractSchema)
async def get_contract(contract_id: int, db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    contract = await db.get(Contract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return ContractSchema.model_validate(contract)


@router.post("/contracts/generate", response_model=ContractSchema)
async def generate_contract_endpoint(
    req: ContractGenerateRequest, db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user),
):
    contract = await create_contract_from_conversation(
        db,
        req.conversation_id,
        template_id=req.template_id,
        output_language=req.language,
    )
    if not contract:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ContractSchema.model_validate(contract)


def _ensure_contract_templates_dir():
    """Subdirectory under FILE_STORAGE_DIR for Word contract templates."""
    d = os.path.join(settings.FILE_STORAGE_DIR, "contract_templates")
    os.makedirs(d, exist_ok=True)
    return d


@router.get("/contract-templates", response_model=list[ContractTemplateSchema])
async def list_contract_templates(
    db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user),
):
    result = await db.execute(select(ContractTemplate).order_by(desc(ContractTemplate.created_at)))
    return [ContractTemplateSchema.model_validate(t) for t in result.scalars().all()]


@router.post("/contract-templates/upload", response_model=ContractTemplateSchema)
async def upload_contract_template(
    file: UploadFile = File(...),
    name: str = Query(..., description="Display name for the template"),
    description: str = Query(""),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    orig = (file.filename or "").lower()
    if not orig.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    _ensure_contract_templates_dir()
    ext = os.path.splitext(file.filename or "template")[1] or ".docx"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    base = _ensure_contract_templates_dir()
    file_path = os.path.join(base, unique_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    entry = ContractTemplate(
        name=name.strip() or "template",
        description=description or "",
        filename=unique_name,
        original_name=file.filename or "template.docx",
        file_path=file_path,
        file_size=len(content),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return ContractTemplateSchema.model_validate(entry)


@router.get("/contract-templates/{template_id}/download")
async def download_contract_template(
    template_id: int, db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user),
):
    entry = await db.get(ContractTemplate, template_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Template not found")
    if not os.path.exists(entry.file_path):
        raise HTTPException(status_code=404, detail="File missing from disk")
    return FileResponse(
        path=entry.file_path,
        filename=entry.original_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.delete("/contract-templates/{template_id}")
async def delete_contract_template(
    template_id: int, db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user),
):
    entry = await db.get(ContractTemplate, template_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Template not found")
    if os.path.exists(entry.file_path):
        os.remove(entry.file_path)
    await db.delete(entry)
    await db.commit()
    return {"status": "deleted"}


@router.put("/contracts/{contract_id}", response_model=ContractSchema)
async def update_contract(
    contract_id: int, req: ContractUpdateRequest,
    db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user),
):
    contract = await db.get(Contract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if req.title is not None:
        contract.title = req.title
    if req.content is not None:
        contract.content = req.content
    if req.status is not None:
        contract.status = req.status
    await db.commit()
    await db.refresh(contract)
    return ContractSchema.model_validate(contract)


@router.delete("/contracts/{contract_id}")
async def delete_contract(contract_id: int, db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    contract = await db.get(Contract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await db.delete(contract)
    await db.commit()
    return {"status": "deleted"}


# ─── LLM Settings ────────────────────────────────────────────────────────────

@router.get("/settings/llm", response_model=LLMSettingsSchema)
async def get_settings_llm(_: str = Depends(get_current_user)):
    cfg = await get_llm_settings()
    masked_key = cfg.get("llm_api_key", "")
    if len(masked_key) > 8:
        masked_key = masked_key[:4] + "****" + masked_key[-4:]
    masked_emb_key = cfg.get("embedding_api_key", "")
    if len(masked_emb_key) > 8:
        masked_emb_key = masked_emb_key[:4] + "****" + masked_emb_key[-4:]
    masked_image_key = cfg.get("image_api_key", "")
    if len(masked_image_key) > 8:
        masked_image_key = masked_image_key[:4] + "****" + masked_image_key[-4:]

    return LLMSettingsSchema(
        provider=cfg.get("llm_provider", "openai"),
        api_key=masked_key,
        base_url=cfg.get("llm_base_url", ""),
        model=cfg.get("llm_model", "gpt-4o"),
        embedding_model=cfg.get("embedding_model", "text-embedding-3-small"),
        embedding_base_url=cfg.get("embedding_base_url", ""),
        embedding_api_key=masked_emb_key,
        image_model=cfg.get("image_model", "gpt-image-1"),
        image_base_url=cfg.get("image_base_url", cfg.get("llm_base_url", "")),
        image_api_key=masked_image_key,
        image_size=cfg.get("image_size", "1536x1024"),
        image_quality=cfg.get("image_quality", "high"),
        image_style=cfg.get("image_style", "natural"),
        temperature=float(cfg.get("llm_temperature", "0.7")),
        max_tokens=int(cfg.get("llm_max_tokens", "1000")),
    )


@router.put("/settings/llm", response_model=LLMSettingsSchema)
async def update_settings_llm(req: LLMSettingsUpdateRequest, _: str = Depends(get_current_user)):
    updates = {}
    if req.provider is not None:
        updates["llm_provider"] = req.provider
    if req.api_key is not None and "****" not in req.api_key:
        updates["llm_api_key"] = req.api_key
    if req.base_url is not None:
        updates["llm_base_url"] = req.base_url
    if req.model is not None:
        updates["llm_model"] = req.model
    if req.embedding_model is not None:
        updates["embedding_model"] = req.embedding_model
    if req.embedding_base_url is not None:
        updates["embedding_base_url"] = req.embedding_base_url
    if req.embedding_api_key is not None and "****" not in req.embedding_api_key:
        updates["embedding_api_key"] = req.embedding_api_key
    if req.image_model is not None:
        updates["image_model"] = req.image_model
    if req.image_base_url is not None:
        updates["image_base_url"] = req.image_base_url
    if req.image_api_key is not None and "****" not in req.image_api_key:
        updates["image_api_key"] = req.image_api_key
    if req.image_size is not None:
        updates["image_size"] = req.image_size
    if req.image_quality is not None:
        updates["image_quality"] = req.image_quality
    if req.image_style is not None:
        updates["image_style"] = req.image_style
    if req.temperature is not None:
        updates["llm_temperature"] = str(req.temperature)
    if req.max_tokens is not None:
        updates["llm_max_tokens"] = str(req.max_tokens)

    if updates:
        await save_llm_settings(updates)

    return await get_settings_llm(_)


@router.post("/settings/llm/test")
async def test_llm_endpoint(req: LLMSettingsUpdateRequest, _: str = Depends(get_current_user)):
    cfg = await get_llm_settings()
    provider = req.provider or cfg.get("llm_provider", "openai")
    api_key = req.api_key if (req.api_key and "****" not in req.api_key) else cfg.get("llm_api_key", "")
    base_url = req.base_url or cfg.get("llm_base_url", "")
    model = req.model or cfg.get("llm_model", "gpt-4o")
    return await test_llm_connection(provider, api_key, base_url, model)


@router.post("/settings/llm/test-embedding")
async def test_embedding_endpoint(req: LLMSettingsUpdateRequest, _: str = Depends(get_current_user)):
    cfg = await get_llm_settings()
    api_key = req.embedding_api_key if (req.embedding_api_key and "****" not in req.embedding_api_key) else cfg.get("embedding_api_key", "") or cfg.get("llm_api_key", "")
    base_url = req.embedding_base_url or cfg.get("embedding_base_url", "") or cfg.get("llm_base_url", "")
    model = req.embedding_model or cfg.get("embedding_model", "text-embedding-3-small")
    return await test_embedding_connection(api_key, base_url, model)


@router.post("/settings/llm/test-image")
async def test_image_endpoint(req: LLMSettingsUpdateRequest, _: str = Depends(get_current_user)):
    cfg = await get_llm_settings()
    api_key = req.image_api_key if (req.image_api_key and "****" not in req.image_api_key) else cfg.get("image_api_key", "") or cfg.get("llm_api_key", "")
    base_url = req.image_base_url or cfg.get("image_base_url", "") or cfg.get("llm_base_url", "")
    model = req.image_model or cfg.get("image_model", "gpt-image-1")
    size = req.image_size or cfg.get("image_size", "1536x1024")
    quality = req.image_quality or cfg.get("image_quality", "high")
    return await test_image_connection(api_key, base_url, model, size, quality)


# ─── File Library ─────────────────────────────────────────────────────────────

def _ensure_upload_dir():
    os.makedirs(settings.FILE_STORAGE_DIR, exist_ok=True)


@router.get("/files", response_model=list[FileEntrySchema])
async def list_files(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = 0, limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    query = select(FileEntry).order_by(desc(FileEntry.created_at))
    if category:
        query = query.where(FileEntry.category == category)
    if search:
        query = query.where(
            (FileEntry.original_name.ilike(f"%{search}%"))
            | (FileEntry.description.ilike(f"%{search}%"))
            | (FileEntry.tags.ilike(f"%{search}%"))
        )
    result = await db.execute(query.offset(skip).limit(limit))
    return [FileEntrySchema.model_validate(f) for f in result.scalars().all()]


@router.post("/files/upload", response_model=FileEntrySchema)
async def upload_file(
    file: UploadFile = File(...),
    description: str = Query(""),
    tags: str = Query(""),
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    _ensure_upload_dir()
    ext = os.path.splitext(file.filename or "file")[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(settings.FILE_STORAGE_DIR, unique_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    entry = FileEntry(
        filename=unique_name,
        original_name=file.filename or "unnamed",
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type,
        description=description,
        tags=tags,
        category=category,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    await add_file_to_index(entry.id, entry.original_name, entry.description, entry.tags, entry.category)
    return FileEntrySchema.model_validate(entry)


@router.put("/files/{file_id}", response_model=FileEntrySchema)
async def update_file(
    file_id: int, req: FileEntryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    entry = await db.get(FileEntry, file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    if req.description is not None:
        entry.description = req.description
    if req.tags is not None:
        entry.tags = req.tags
    if req.category is not None:
        entry.category = req.category
    await db.commit()
    await db.refresh(entry)
    await add_file_to_index(entry.id, entry.original_name, entry.description, entry.tags, entry.category)
    return FileEntrySchema.model_validate(entry)


@router.delete("/files/{file_id}")
async def delete_file(file_id: int, db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    entry = await db.get(FileEntry, file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    if os.path.exists(entry.file_path):
        os.remove(entry.file_path)
    await remove_file_from_index(file_id)
    await db.delete(entry)
    await db.commit()
    return {"status": "deleted"}


@router.get("/files/{file_id}/download")
async def download_file(file_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(FileEntry, file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(entry.file_path):
        raise HTTPException(status_code=404, detail="File missing from disk")
    return FileResponse(
        path=entry.file_path,
        filename=entry.original_name,
        media_type=entry.mime_type or "application/octet-stream",
    )


# ─── Telegram Bot Management ─────────────────────────────────────────────────

def _mask_token(token: str) -> str:
    if len(token) > 12:
        return token[:6] + "****" + token[-4:]
    return "****"


def _bot_to_schema(bot: TelegramBot) -> TelegramBotSchema:
    return TelegramBotSchema(
        id=bot.id,
        name=bot.name,
        token_masked=_mask_token(bot.token),
        admin_chat_id=bot.admin_chat_id or "",
        welcome_message=bot.welcome_message or "",
        is_active=bot.is_active,
        bot_username=bot.bot_username,
        description=bot.description or "",
        is_running=bot_manager.is_running(bot.id),
        created_at=bot.created_at,
        updated_at=bot.updated_at,
    )


@router.get("/bots", response_model=list[TelegramBotSchema])
async def list_bots(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    result = await db.execute(select(TelegramBot).order_by(desc(TelegramBot.created_at)))
    return [_bot_to_schema(b) for b in result.scalars().all()]


@router.post("/bots", response_model=TelegramBotSchema)
async def create_bot(
    req: TelegramBotCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    existing = await db.execute(
        select(TelegramBot).where(TelegramBot.token == req.token)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该 Token 已被使用")

    bot = TelegramBot(
        name=req.name,
        token=req.token,
        admin_chat_id=req.admin_chat_id,
        welcome_message=req.welcome_message,
        is_active=req.is_active,
        description=req.description,
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)

    if bot.is_active:
        await bot_manager.start_bot(bot.id, bot.token)

    return _bot_to_schema(bot)


@router.get("/bots/{bot_id}", response_model=TelegramBotSchema)
async def get_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    bot = await db.get(TelegramBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return _bot_to_schema(bot)


@router.put("/bots/{bot_id}", response_model=TelegramBotSchema)
async def update_bot(
    bot_id: int,
    req: TelegramBotUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    bot = await db.get(TelegramBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    token_changed = False
    if req.name is not None:
        bot.name = req.name
    if req.token is not None and req.token != bot.token:
        dup = await db.execute(
            select(TelegramBot).where(TelegramBot.token == req.token, TelegramBot.id != bot_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="该 Token 已被其他 Bot 使用")
        bot.token = req.token
        token_changed = True
    if req.admin_chat_id is not None:
        bot.admin_chat_id = req.admin_chat_id
    if req.welcome_message is not None:
        bot.welcome_message = req.welcome_message
    if req.description is not None:
        bot.description = req.description
    if req.is_active is not None:
        bot.is_active = req.is_active

    await db.commit()
    await db.refresh(bot)

    if token_changed or (req.is_active is not None):
        if bot.is_active:
            await bot_manager.stop_bot(bot.id)
            await bot_manager.start_bot(bot.id, bot.token)
        else:
            await bot_manager.stop_bot(bot.id)

    return _bot_to_schema(bot)


@router.delete("/bots/{bot_id}")
async def delete_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    bot = await db.get(TelegramBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    await bot_manager.stop_bot(bot_id)
    await db.delete(bot)
    await db.commit()
    return {"status": "deleted"}


@router.post("/bots/{bot_id}/start")
async def start_bot_endpoint(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    bot = await db.get(TelegramBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    ok = await bot_manager.start_bot(bot.id, bot.token)
    if not ok:
        raise HTTPException(status_code=500, detail="启动 Bot 失败，请检查 Token 是否正确")
    return {"status": "started", "is_running": True}


@router.post("/bots/{bot_id}/stop")
async def stop_bot_endpoint(
    bot_id: int,
    _: str = Depends(get_current_user),
):
    ok = await bot_manager.stop_bot(bot_id)
    return {"status": "stopped" if ok else "not_running", "is_running": False}


# ─── Products ────────────────────────────────────────────────────────────────

@router.get("/products/meta")
async def get_products_meta(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Return distinct values for filter dropdowns."""
    from sqlalchemy import distinct

    async def _distinct(col):
        r = await db.execute(select(distinct(col)).where(col != "").order_by(col))
        return [row[0] for row in r.fetchall() if row[0]]

    spaces = await _distinct(ProductEntry.space)
    styles = await _distinct(ProductEntry.style)
    series = await _distinct(ProductEntry.series_name)
    brands = await _distinct(ProductEntry.brand)
    return {"spaces": spaces, "styles": styles, "series": series, "brands": brands}


@router.get("/products", response_model=list[ProductEntryListSchema])
async def list_products(
    keyword: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    space: Optional[str] = Query(None),
    style: Optional[str] = Query(None),
    series: Optional[str] = Query(None),
    color: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    query = select(ProductEntry).options(selectinload(ProductEntry.images))
    if keyword:
        kw = f"%{keyword}%"
        from sqlalchemy import or_
        query = query.where(
            or_(
                ProductEntry.product_name.ilike(kw),
                ProductEntry.series_name.ilike(kw),
                ProductEntry.description_text.ilike(kw),
            )
        )
    if brand:
        query = query.where(ProductEntry.brand == brand)
    if space:
        query = query.where(ProductEntry.space == space)
    if style:
        query = query.where(ProductEntry.style == style)
    if series:
        query = query.where(ProductEntry.series_name == series)
    if color:
        query = query.where(ProductEntry.color.ilike(f"%{color}%"))
    query = query.order_by(ProductEntry.id).offset(skip).limit(limit)
    result = await db.execute(query)
    entries = result.scalars().all()

    out = []
    for e in entries:
        first_img = e.images[0].local_path if e.images else None
        out.append(ProductEntryListSchema(
            id=e.id,
            brand=e.brand,
            product_id_ext=e.product_id_ext,
            product_name=e.product_name,
            series_name=e.series_name,
            space=e.space,
            style=e.style,
            color=e.color,
            material=e.material,
            size=e.size,
            price_display=e.price_display,
            serial_number=e.serial_number,
            description_text=e.description_text,
            buy_url=e.buy_url,
            first_image_path=first_img,
            created_at=e.created_at,
            updated_at=e.updated_at,
        ))
    return out


@router.get("/products/{product_id}", response_model=ProductEntrySchema)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    result = await db.execute(
        select(ProductEntry)
        .options(selectinload(ProductEntry.images))
        .where(ProductEntry.id == product_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductEntrySchema.model_validate(entry)


@router.get("/products/{product_id}/images/{order}")
async def get_product_image(
    product_id: int,
    order: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProductImage).where(
            ProductImage.product_entry_id == product_id,
            ProductImage.display_order == order,
        )
    )
    img = result.scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    # local_path is stored as "uploads/products/..." relative to /app inside the container
    full_path = os.path.join("/app", img.local_path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Image file missing from disk")
    ext = os.path.splitext(full_path)[1].lower()
    mime = {"jpg": "image/jpeg", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    return FileResponse(path=full_path, media_type=mime)


def _record_to_schema(record_dict: dict) -> SceneGenerationRecordSchema:
    return SceneGenerationRecordSchema.model_validate(record_dict)


@router.get("/products/{product_id}/scene-images", response_model=list[SceneGenerationRecordSchema])
async def list_product_scene_images(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    result = await db.execute(
        select(SceneGenerationRecord)
        .where(SceneGenerationRecord.primary_product_id == product_id)
        .order_by(desc(SceneGenerationRecord.created_at))
        .limit(20)
    )
    records = result.scalars().all()
    out = []
    for record in records:
        out.append(_record_to_schema(await build_scene_record_response(record)))
    return out


@router.post("/products/{product_id}/scene-images", response_model=SceneGenerationRecordSchema)
async def create_product_scene_images(
    product_id: int,
    req: SceneGenerationRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    product = await db.get(ProductEntry, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    result = await db.execute(select(ProductEntry).order_by(ProductEntry.id))
    entries = result.scalars().all()
    all_products = [
        {
            "id": e.id,
            "name": e.product_name,
            "space": e.space,
            "style": e.style,
            "color": e.color,
            "material": e.material,
            "buy_url": e.buy_url,
            "detail_url": e.detail_url,
        }
        for e in entries
    ]
    record = await generate_scene_images(
        primary_product=product,
        all_products=all_products,
        user_request=req.user_request or "",
        scene_name=req.scene_name or "",
        style_hint=req.style_hint or "",
        related_product_ids=req.related_product_ids or None,
        conversation_id=req.conversation_id,
    )
    return _record_to_schema(await build_scene_record_response(record))


@router.get("/scene-generations/{record_id}/images/{index}")
async def get_scene_generation_image(
    record_id: int,
    index: int,
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(SceneGenerationRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scene generation record not found")
    image_result = await db.execute(
        select(SceneGenerationImage)
        .where(
            SceneGenerationImage.record_id == record_id,
            SceneGenerationImage.image_index == index,
        )
        .limit(1)
    )
    scene_image = image_result.scalar_one_or_none()
    if scene_image:
        return Response(content=scene_image.binary_data, media_type=scene_image.mime_type or "image/png")
    paths = json.loads(record.output_paths_json or "[]")
    if index < 0 or index >= len(paths):
        raise HTTPException(status_code=404, detail="Scene image not found")
    full_path = os.path.join("/app", paths[index])
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Scene image file missing from disk")
    ext = os.path.splitext(full_path)[1].lower()
    mime = {"jpg": "image/jpeg", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    return FileResponse(path=full_path, media_type=mime)


@router.post("/products/import")
async def trigger_product_import(
    _: str = Depends(get_current_user),
):
    """Trigger re-import of product data from mounted Furniture-Crawler CSV + images."""
    import subprocess
    script = "/app/scripts/import_products.py"
    if not os.path.exists(script):
        raise HTTPException(status_code=500, detail="Import script not found")
    proc = subprocess.run(
        ["python", script],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr[-2000:])
    return {"status": "ok", "output": proc.stdout[-2000:]}


# ─── Scene Generator ─────────────────────────────────────────────────────────

@router.post("/scene-generator/generate", response_model=SceneGenerationRecordSchema)
async def scene_generator_generate(
    req: SceneGeneratorRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    if not req.product_image_refs or len(req.product_image_refs) > 4:
        raise HTTPException(status_code=400, detail="请选择 1~4 张产品图片")

    product_ids = list(dict.fromkeys(ref.product_id for ref in req.product_image_refs))
    result = await db.execute(
        select(ProductEntry).where(ProductEntry.id.in_(product_ids))
    )
    products_map = {p.id: p for p in result.scalars().all()}
    if not products_map:
        raise HTTPException(status_code=404, detail="未找到所选产品")

    primary_product = products_map[product_ids[0]]
    related_ids = [pid for pid in product_ids[1:] if pid in products_map]

    all_result = await db.execute(select(ProductEntry).order_by(ProductEntry.id))
    all_products = [
        {
            "id": e.id,
            "name": e.product_name,
            "space": e.space,
            "style": e.style,
            "color": e.color,
            "material": e.material,
            "buy_url": e.buy_url,
            "detail_url": e.detail_url,
        }
        for e in all_result.scalars().all()
    ]

    record = await start_scene_generation(
        primary_product=primary_product,
        all_products=all_products,
        user_request=req.user_request or "",
        scene_name=req.scene_name or "",
        style_hint=req.style_hint or "",
        related_product_ids=related_ids or None,
    )
    return _record_to_schema(await build_scene_record_response(record))


@router.post("/scene-generations/{record_id}/toggle-library")
async def toggle_scene_library(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    record = await db.get(SceneGenerationRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scene record not found")
    record.in_library = not record.in_library
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "in_library": record.in_library}


@router.delete("/scene-generations/{record_id}")
async def delete_scene_generation(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    record = await db.get(SceneGenerationRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scene record not found")

    await db.execute(delete(SceneGenerationImage).where(SceneGenerationImage.record_id == record_id))
    await db.delete(record)
    await db.commit()

    scene_dir = os.path.join(settings.FILE_STORAGE_DIR, "generated_scenes", str(record_id))
    shutil.rmtree(scene_dir, ignore_errors=True)
    return {"status": "deleted", "id": record_id}


def _scene_view_clause(view: str):
    if view == "review":
        return (SceneGenerationRecord.status == "completed") & (SceneGenerationRecord.in_library == False)
    if view == "generating":
        return SceneGenerationRecord.status.in_(["pending", "failed"])
    return (SceneGenerationRecord.status == "completed") & (SceneGenerationRecord.in_library == True)


@router.get("/scene-generations/{record_id}", response_model=SceneGenerationRecordSchema)
async def get_scene_generation(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    record = await db.get(SceneGenerationRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scene record not found")
    return _record_to_schema(await build_scene_record_response(record))


# ─── Scene Library ───────────────────────────────────────────────────────────

@router.get("/scene-library/filters")
async def scene_library_filters(
    view: str = Query("library", pattern="^(library|review|generating)$"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    lib_filter = _scene_view_clause(view)

    result = await db.execute(
        select(func.distinct(ProductEntry.brand))
        .join(SceneGenerationRecord, SceneGenerationRecord.primary_product_id == ProductEntry.id)
        .where(lib_filter)
    )
    brands = sorted(b for (b,) in result.all() if b)

    result = await db.execute(
        select(func.distinct(ProductEntry.space))
        .join(SceneGenerationRecord, SceneGenerationRecord.primary_product_id == ProductEntry.id)
        .where(lib_filter)
    )
    spaces = sorted(s for (s,) in result.all() if s)

    result = await db.execute(
        select(func.distinct(ProductEntry.style))
        .join(SceneGenerationRecord, SceneGenerationRecord.primary_product_id == ProductEntry.id)
        .where(lib_filter)
    )
    styles = sorted(s for (s,) in result.all() if s)

    result = await db.execute(
        select(func.distinct(SceneGenerationRecord.scene_name))
        .where(lib_filter)
    )
    scene_names = sorted(s for (s,) in result.all() if s)

    return {"brands": brands, "spaces": spaces, "styles": styles, "scene_names": scene_names}


@router.get("/scene-library", response_model=list[SceneLibraryItemSchema])
async def list_scene_library(
    view: str = Query("library", pattern="^(library|review|generating)$"),
    brand: Optional[str] = Query(None),
    space: Optional[str] = Query(None),
    style: Optional[str] = Query(None),
    scene_name: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    query = (
        select(SceneGenerationRecord)
        .join(ProductEntry, SceneGenerationRecord.primary_product_id == ProductEntry.id)
        .where(_scene_view_clause(view))
    )
    if brand:
        query = query.where(ProductEntry.brand == brand)
    if space:
        query = query.where(ProductEntry.space == space)
    if style:
        query = query.where(ProductEntry.style == style)
    if scene_name:
        query = query.where(SceneGenerationRecord.scene_name == scene_name)

    query = query.order_by(desc(SceneGenerationRecord.created_at)).offset(skip).limit(limit)
    result = await db.execute(query)
    records = result.scalars().all()

    items: list[SceneLibraryItemSchema] = []
    for record in records:
        resp = await build_scene_record_response(record)
        primary = await db.get(ProductEntry, record.primary_product_id)
        image_urls = resp.get("image_urls", [])
        items.append(SceneLibraryItemSchema(
            id=record.id,
            conversation_id=record.conversation_id,
            primary_product_id=record.primary_product_id,
            primary_product_name=resp.get("primary_product_name", ""),
            primary_product_brand=primary.brand if primary else "",
            primary_product_space=primary.space if primary else "",
            primary_product_style=primary.style if primary else "",
            scene_name=record.scene_name or "",
            style_hint=record.style_hint or "",
            request_text=record.request_text or "",
            related_products=resp.get("related_products", []),
            image_urls=image_urls,
            cover_url=image_urls[0] if image_urls else "",
            duration_ms=record.duration_ms or 0,
            status=record.status or "",
            in_library=bool(record.in_library),
            error_message=record.error_message or "",
            created_at=record.created_at,
            updated_at=record.updated_at,
        ))
    return items
