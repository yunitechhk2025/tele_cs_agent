import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=20, max_overflow=10)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def _run_migrations(conn):
    migrations = [
        (
            "conversations", "bot_id",
            "ALTER TABLE conversations ADD COLUMN bot_id INTEGER REFERENCES telegram_bots(id)"
        ),
        (
            "conversations", "quote_language",
            "ALTER TABLE conversations ADD COLUMN quote_language VARCHAR(10)"
        ),
        (
            "messages", "attachment_file_id",
            "ALTER TABLE messages ADD COLUMN attachment_file_id INTEGER"
        ),
        (
            "product_images", "source_url",
            "ALTER TABLE product_images ADD COLUMN source_url VARCHAR(2000) DEFAULT ''"
        ),
        (
            "scene_generation_records", "in_library",
            "ALTER TABLE scene_generation_records ADD COLUMN in_library BOOLEAN DEFAULT FALSE"
        ),
    ]
    for table, column, ddl in migrations:
        result = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ), {"table": table, "column": column})
        if result.fetchone() is None:
            logger.info(f"Running migration: adding {table}.{column}")
            conn.execute(text(ddl))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_run_migrations)
