import logging
import os
import re
import chromadb
from chromadb.config import Settings as ChromaSettings
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import KnowledgeEntry
from app.services.llm_service import get_embedding

logger = logging.getLogger(__name__)
settings = get_settings()

# Chroma 0.5+: use PersistentClient so vectors survive restarts. The legacy Client() with
# persist_directory is unreliable and can behave like an in-memory store.
os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
chroma_client = chromadb.PersistentClient(
    path=settings.CHROMA_PERSIST_DIR,
    settings=ChromaSettings(anonymized_telemetry=False),
)

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
    raw = f"{title}\n\n{content}"
    # OpenAI embeddings have input length limits; truncate to avoid silent [] embedding failures.
    full_text = raw[:24000] if len(raw) > 24000 else raw
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


async def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """Retrieve nearest knowledge chunks by embedding. Uses top_k results as-is; do not
    filter by a hard distance cutoff — Chroma's metric (cosine vs L2) and embedding scale
    vary, and an overly tight threshold was dropping all hits so RAG appeared empty."""
    embedding = await get_embedding(query)
    if not embedding:
        logger.warning("Knowledge base search skipped: embedding API returned no vector")
        return ""
    try:
        count = kb_collection.count()
        if count == 0:
            logger.info("KB semantic: Chroma knowledge_base count=0 (nothing indexed yet)")
            return ""
        n_results = min(top_k, count)
        results = kb_collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
        )
        if not results["documents"] or not results["documents"][0]:
            logger.warning("KB semantic: query returned no documents despite count=%s", count)
            return ""
        docs = results["documents"][0]
        dists = results.get("distances") or []
        if dists and dists[0]:
            logger.debug(
                "KB search: n=%s distances=%s",
                len(docs),
                [round(float(d), 4) for d in dists[0][: min(5, len(dists[0]))]],
            )
        ctx = "\n\n---\n\n".join(docs)
        logger.info("KB semantic: %d chunks from Chroma, %d chars context", len(docs), len(ctx))
        return ctx
    except Exception as e:
        logger.error(f"Knowledge base search failed: {e}")
        return ""


async def search_knowledge_keyword_fallback(query: str, limit: int = 5) -> str:
    """When Chroma is empty or embeddings miss, score knowledge_entries with lexical terms.

    Chinese user questions often arrive as one continuous token like "你们公司的隐私政策是什么".
    A plain ILIKE on that whole sentence misses entries titled "隐私政策", so we extract
    domain phrases and short Chinese n-grams, then rank rows in Python.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return ""

    def unique_terms(items: list[str]) -> list[str]:
        seen: set[str] = set()
        terms: list[str] = []
        for item in items:
            term = (item or "").strip().lower()
            if len(term) < 2 or term in seen:
                continue
            seen.add(term)
            terms.append(term)
        return terms

    domain_groups = [
        ["隐私政策", "隐私", "个人信息", "个人资料", "信息安全", "数据保护", "privacy", "personal information"],
        ["退货政策", "完整退货政策", "退货", "退换货", "退款", "换货", "return policy", "return", "refund", "exchange"],
        ["保修条款", "保修", "质保", "售后", "维修", "warranty", "guarantee", "repair"],
        ["发货时效", "物流追踪", "物流", "配送", "发货", "送货", "运费", "shipping", "delivery"],
        ["订单状态", "订单状态查询", "订单", "order status"],
    ]
    terms: list[str] = []
    q_lower = q.lower()
    for group in domain_groups:
        if any(alias.lower() in q_lower for alias in group):
            terms.extend(group)

    terms.extend(re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,}", q_lower))
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", q)
    stop_terms = {
        "你们", "我们", "公司", "贵司", "这个", "那个", "什么", "是什么", "多少", "怎么",
        "如何", "一下", "请问", "有没有", "能不能", "可以", "的吗", "政策",
    }
    for run in chinese_runs:
        if run in stop_terms:
            continue
        for size in (4, 3, 2):
            if len(run) < size:
                continue
            for idx in range(0, len(run) - size + 1):
                gram = run[idx:idx + size]
                if gram not in stop_terms:
                    terms.append(gram)

    tokens = unique_terms(terms)
    if not tokens:
        return ""
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(KnowledgeEntry).order_by(KnowledgeEntry.id.desc()).limit(500)
            result = await db.execute(stmt)
            rows = result.scalars().all()
            scored = []
            for row in rows:
                title = (row.title or "").lower()
                category = (row.category or "").lower()
                content = (row.content or "").lower()
                score = 0
                for term in tokens:
                    if term in title:
                        score += 8
                    if term in category:
                        score += 5
                    if term in content:
                        score += 1
                if score > 0:
                    scored.append((score, row.id, row))
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            if not scored:
                logger.info("KB keyword fallback: no match for tokens=%s", tokens[:20])
                return ""
            matched = [row for _, _, row in scored[:limit]]
            logger.info(
                "KB keyword fallback: matched ids=%s tokens=%s",
                [row.id for row in matched],
                tokens[:20],
            )
            parts = [f"{r.title}\n\n{r.content}" for r in matched]
            return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.error(f"KB keyword fallback failed: {e}")
        return ""


async def search_knowledge_for_bot(query: str) -> str:
    """Semantic Chroma first; if empty, keyword match on PostgreSQL knowledge_entries."""
    text = await search_knowledge_base(query)
    if text.strip():
        return text
    fallback = await search_knowledge_keyword_fallback(query)
    if fallback.strip():
        logger.info("KB: using keyword fallback, %d chars (Chroma empty or semantic miss)", len(fallback))
    else:
        logger.info("KB: no retrieval (semantic empty, keyword empty)")
    return fallback


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
