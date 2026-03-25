import logging
import os

from docx import Document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Conversation, Contract, ContractTemplate
from app.services.llm_service import generate_contract

logger = logging.getLogger(__name__)


def extract_docx_text(file_path: str) -> str:
    """Read plain text from a .docx file (paragraphs and table cells)."""
    doc = Document(file_path)
    parts: list[str] = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts) if parts else ""


async def create_contract_from_conversation(
    db: AsyncSession,
    conversation_id: int,
    template_id: int | None = None,
    output_language: str | None = None,
) -> Contract | None:
    """Generate a contract draft from a conversation's chat history."""
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        return None

    chat_history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in conversation.messages
    ]

    customer_name = " ".join(
        filter(None, [conversation.first_name, conversation.last_name])
    ) or conversation.username or f"Customer #{conversation.telegram_user_id}"

    template_content: str | None = None
    if template_id is not None:
        template = await db.get(ContractTemplate, template_id)
        if template and template.file_path and os.path.exists(template.file_path):
            try:
                template_content = extract_docx_text(template.file_path)
            except Exception as e:
                logger.error(f"Failed to read template {template_id}: {e}")
                template_content = None
        elif template_id is not None:
            logger.warning(f"Template {template_id} not found or file missing")

    lang = (output_language or "").strip() or conversation.language or "en"

    contract_content = await generate_contract(
        chat_history=chat_history,
        customer_name=customer_name,
        language=lang,
        template_content=template_content,
    )

    title_line = contract_content.split("\n")[0].strip("# ").strip()
    contract = Contract(
        conversation_id=conversation_id,
        title=title_line[:500],
        content=contract_content,
        status="draft",
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    return contract
