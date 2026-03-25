import logging
from typing import Optional

from telegram import Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import TelegramBot

logger = logging.getLogger(__name__)

_running_bots: dict[int, Application] = {}


def _make_handlers(bot_id: int):
    from app.telegram_bot import make_start_handler, make_message_handler, make_close_handler
    return [
        CommandHandler("start", make_start_handler(bot_id)),
        CommandHandler("close", make_close_handler(bot_id)),
        MessageHandler(filters.TEXT & ~filters.COMMAND, make_message_handler(bot_id)),
    ]


async def start_bot(bot_id: int, token: str) -> bool:
    if bot_id in _running_bots:
        logger.info(f"Bot {bot_id} already running, restarting...")
        await stop_bot(bot_id)

    try:
        app = Application.builder().token(token).build()
        for handler in _make_handlers(bot_id):
            app.add_handler(handler)

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        _running_bots[bot_id] = app

        try:
            bot_info = await app.bot.get_me()
            async with AsyncSessionLocal() as db:
                bot_record = await db.get(TelegramBot, bot_id)
                if bot_record:
                    bot_record.bot_username = bot_info.username
                    await db.commit()
        except Exception:
            pass

        logger.info(f"Bot {bot_id} started successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to start bot {bot_id}: {e}")
        return False


async def stop_bot(bot_id: int) -> bool:
    app = _running_bots.pop(bot_id, None)
    if not app:
        return False
    try:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info(f"Bot {bot_id} stopped")
        return True
    except Exception as e:
        logger.error(f"Error stopping bot {bot_id}: {e}")
        return False


async def start_all_active_bots():
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TelegramBot).where(TelegramBot.is_active == True)
            )
            bots = result.scalars().all()

        started = 0
        for bot in bots:
            if bot.token and bot.token not in ("", "your_bot_token_here"):
                ok = await start_bot(bot.id, bot.token)
                if ok:
                    started += 1
        logger.info(f"Started {started}/{len(bots)} active bots")
    except Exception as e:
        logger.error(f"Failed to start bots: {e}")


async def stop_all_bots():
    bot_ids = list(_running_bots.keys())
    for bid in bot_ids:
        await stop_bot(bid)
    logger.info("All bots stopped")


def get_bot_instance(bot_id: int) -> Optional[Bot]:
    app = _running_bots.get(bot_id)
    return app.bot if app else None


def is_running(bot_id: int) -> bool:
    return bot_id in _running_bots


def get_running_bot_ids() -> list[int]:
    return list(_running_bots.keys())


def get_any_bot_instance() -> Optional[Bot]:
    if _running_bots:
        return next(iter(_running_bots.values())).bot
    return None
