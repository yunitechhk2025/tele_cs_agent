import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select

from app.config import get_settings
from app.database import init_db, AsyncSessionLocal
from app.models import TelegramBot
from app.api.router import router
from app.services.llm_service import load_llm_settings
from app.services.customer_service_service import restore_pending_ai_reply_tasks
from app.services import bot_manager


async def _seed_default_simulator_bot() -> None:
    """Ensure there's at least one bot available so the Telegram simulator
    has something to default to. The seeded bot is inactive so the bot
    manager won't try to connect to Telegram with a placeholder token."""
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(TelegramBot).limit(1))
        if existing.scalars().first() is not None:
            return
        bot = TelegramBot(
            name="YUNIbot",
            token="simulator-only-yunibot-placeholder",
            admin_chat_id="",
            welcome_message="Hi! I'm YUNIbot, your AI customer service assistant. How can I help you today?",
            description="默认模拟测试用 Bot（无真实 Telegram token，仅用于内置模拟器）。",
            bot_username="yunibot",
            is_active=False,
        )
        session.add(bot)
        await session.commit()
        logger.info("Seeded default simulator bot: YUNIbot")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")

    os.makedirs(settings.FILE_STORAGE_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)

    await load_llm_settings()
    logger.info("LLM settings loaded")

    await restore_pending_ai_reply_tasks()
    logger.info("Pending AI reply tasks restored")

    try:
        await _seed_default_simulator_bot()
    except Exception as exc:
        logger.warning("Failed to seed default simulator bot: %s", exc)

    await bot_manager.start_all_active_bots()

    yield

    await bot_manager.stop_all_bots()
    logger.info("All bots stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    running = bot_manager.get_running_bot_ids()
    return {"status": "ok", "running_bots": len(running), "bot_ids": running}
