import logging
import chromadb
from chromadb.config import Settings as ChromaSettings
from app.config import get_settings
from app.services.llm_service import get_embedding

logger = logging.getLogger(__name__)
settings = get_settings()

chroma_client = chromadb.Client(ChromaSettings(
    persist_directory=settings.CHROMA_PERSIST_DIR,
    anonymized_telemetry=False,
))

kb_collection = chroma_client.get_or_create_collection(
    name="knowledge_base",
    metadata={"hnsw:space": "cosine"},
)

file_collection = chroma_client.get_or_create_collection(
    name="file_library",
    metadata={"hnsw:space": "cosine"},
)


# ─── Knowledge Base ──────────────────────────────────────────────────────────

async def add_to_knowledge_base(entry_id: int, title: str, content: str, category: str | None = None):
    full_text = f"{title}\n\n{content}"
    embedding = await get_embedding(full_text)
    if not embedding:
        return False
    metadata = {"title": title, "category": category or "general"}
    kb_collection.upsert(
        ids=[str(entry_id)], embeddings=[embedding],
        documents=[full_text], metadatas=[metadata],
    )
    return True


async def remove_from_knowledge_base(entry_id: int):
    try:
        kb_collection.delete(ids=[str(entry_id)])
        return True
    except Exception as e:
        logger.error(f"Failed to remove from knowledge base: {e}")
        return False


async def search_knowledge_base(query: str, top_k: int = 3) -> str:
    embedding = await get_embedding(query)
    if not embedding:
        return ""
    try:
        count = kb_collection.count()
        if count == 0:
            return ""
        results = kb_collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, count),
        )
        if not results["documents"] or not results["documents"][0]:
            return ""
        context_parts = []
        for i, doc in enumerate(results["documents"][0]):
            distance = results["distances"][0][i] if results["distances"] else 0
            if distance < 1.5:
                context_parts.append(doc)
        return "\n\n---\n\n".join(context_parts) if context_parts else ""
    except Exception as e:
        logger.error(f"Knowledge base search failed: {e}")
        return ""


# ─── File Library ─────────────────────────────────────────────────────────────

async def add_file_to_index(file_id: int, name: str, description: str, tags: str, category: str | None = None):
    """Index a file's metadata for semantic search."""
    text = f"{name}\n{description}\n{tags}"
    embedding = await get_embedding(text)
    if not embedding:
        return False
    metadata = {"name": name, "tags": tags, "category": category or "general"}
    file_collection.upsert(
        ids=[str(file_id)], embeddings=[embedding],
        documents=[text], metadatas=[metadata],
    )
    return True


async def remove_file_from_index(file_id: int):
    try:
        file_collection.delete(ids=[str(file_id)])
        return True
    except Exception as e:
        logger.error(f"Failed to remove file from index: {e}")
        return False


async def search_files(query: str, top_k: int = 3) -> list[dict]:
    """Search files by semantic similarity, return list of {id, name, tags, score}."""
    embedding = await get_embedding(query)
    if not embedding:
        return []
    try:
        count = file_collection.count()
        if count == 0:
            return []
        results = file_collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, count),
        )
        if not results["ids"] or not results["ids"][0]:
            return []
        matched = []
        for i, fid in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results["distances"] else 0
            if distance < 1.2:
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                matched.append({
                    "id": int(fid),
                    "name": meta.get("name", ""),
                    "tags": meta.get("tags", ""),
                    "score": round(1 - distance, 3),
                })
        return matched
    except Exception as e:
        logger.error(f"File search failed: {e}")
        return []
