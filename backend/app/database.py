import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
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
            "conversations",
            "bot_id",
            "ALTER TABLE conversations ADD COLUMN bot_id INTEGER REFERENCES telegram_bots(id)",
        ),
        (
            "conversations",
            "quote_language",
            "ALTER TABLE conversations ADD COLUMN quote_language VARCHAR(10)",
        ),
        (
            "messages",
            "attachment_file_id",
            "ALTER TABLE messages ADD COLUMN attachment_file_id INTEGER",
        ),
        (
            "product_images",
            "source_url",
            "ALTER TABLE product_images ADD COLUMN source_url VARCHAR(2000) DEFAULT ''",
        ),
        (
            "scene_generation_records",
            "in_library",
            "ALTER TABLE scene_generation_records ADD COLUMN in_library BOOLEAN DEFAULT FALSE",
        ),
        (
            "pending_ai_replies",
            "auto_send_paused",
            "ALTER TABLE pending_ai_replies ADD COLUMN auto_send_paused BOOLEAN DEFAULT FALSE",
        ),
        (
            "pending_ai_replies",
            "content_kind",
            "ALTER TABLE pending_ai_replies ADD COLUMN content_kind VARCHAR(50) DEFAULT 'text'",
        ),
        (
            "pending_ai_replies",
            "payload_json",
            "ALTER TABLE pending_ai_replies ADD COLUMN payload_json TEXT DEFAULT '{}'",
        ),
        (
            "scene_generation_records",
            "deferred_delivery",
            "ALTER TABLE scene_generation_records ADD COLUMN deferred_delivery BOOLEAN DEFAULT FALSE",
        ),
        (
            "conversation_turn_metrics",
            "primary_intent",
            "ALTER TABLE conversation_turn_metrics ADD COLUMN primary_intent VARCHAR(100) DEFAULT ''",
        ),
        (
            "conversation_turn_metrics",
            "secondary_intents_json",
            "ALTER TABLE conversation_turn_metrics ADD COLUMN secondary_intents_json TEXT DEFAULT '[]'",
        ),
        (
            "conversation_turn_metrics",
            "intent_confidence",
            "ALTER TABLE conversation_turn_metrics ADD COLUMN intent_confidence FLOAT",
        ),
        (
            "conversation_turn_metrics",
            "intent_source",
            "ALTER TABLE conversation_turn_metrics ADD COLUMN intent_source VARCHAR(50) DEFAULT ''",
        ),
        (
            "conversation_turn_metrics",
            "intent_reason",
            "ALTER TABLE conversation_turn_metrics ADD COLUMN intent_reason TEXT DEFAULT ''",
        ),
        (
            "conversation_scene_states",
            "active_product_id",
            "ALTER TABLE conversation_scene_states ADD COLUMN active_product_id INTEGER REFERENCES product_entries(id)",
        ),
        (
            "conversation_scene_states",
            "recent_product_ids_json",
            "ALTER TABLE conversation_scene_states ADD COLUMN recent_product_ids_json TEXT DEFAULT '[]'",
        ),
        (
            "conversation_scene_states",
            "active_topic",
            "ALTER TABLE conversation_scene_states ADD COLUMN active_topic VARCHAR(100) DEFAULT ''",
        ),
        (
            "conversation_scene_states",
            "preferences_json",
            "ALTER TABLE conversation_scene_states ADD COLUMN preferences_json TEXT DEFAULT '{}'",
        ),
        (
            "product_entries",
            "primary_category",
            "ALTER TABLE product_entries ADD COLUMN primary_category VARCHAR(100) DEFAULT ''",
        ),
        (
            "product_entries",
            "secondary_categories_json",
            "ALTER TABLE product_entries ADD COLUMN secondary_categories_json TEXT DEFAULT '[]'",
        ),
        (
            "product_entries",
            "normalized_brand",
            "ALTER TABLE product_entries ADD COLUMN normalized_brand VARCHAR(100) DEFAULT ''",
        ),
        (
            "product_entries",
            "normalized_space",
            "ALTER TABLE product_entries ADD COLUMN normalized_space VARCHAR(100) DEFAULT ''",
        ),
        (
            "product_entries",
            "normalized_style",
            "ALTER TABLE product_entries ADD COLUMN normalized_style VARCHAR(100) DEFAULT ''",
        ),
        (
            "product_entries",
            "normalized_color",
            "ALTER TABLE product_entries ADD COLUMN normalized_color VARCHAR(100) DEFAULT ''",
        ),
        (
            "product_entries",
            "normalized_materials_json",
            "ALTER TABLE product_entries ADD COLUMN normalized_materials_json TEXT DEFAULT '[]'",
        ),
        (
            "product_entries",
            "category_confidence",
            "ALTER TABLE product_entries ADD COLUMN category_confidence FLOAT DEFAULT 0",
        ),
        (
            "product_entries",
            "classification_source",
            "ALTER TABLE product_entries ADD COLUMN classification_source VARCHAR(100) DEFAULT ''",
        ),
        (
            "product_entries",
            "classification_reason",
            "ALTER TABLE product_entries ADD COLUMN classification_reason TEXT DEFAULT ''",
        ),
        (
            "conversation_turn_step_metrics",
            "metadata_json",
            "ALTER TABLE conversation_turn_step_metrics ADD COLUMN metadata_json TEXT DEFAULT '{}'",
        ),
    ]
    for table, column, ddl in migrations:
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        if result.fetchone() is None:
            logger.info(f"Running migration: adding {table}.{column}")
            conn.execute(text(ddl))

    conn.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS product_entry_translations (
            id SERIAL PRIMARY KEY,
            product_entry_id INTEGER NOT NULL REFERENCES product_entries(id) ON DELETE CASCADE,
            language VARCHAR(20) NOT NULL,
            product_name VARCHAR(500) DEFAULT '',
            series_name VARCHAR(500) DEFAULT '',
            space VARCHAR(200) DEFAULT '',
            style VARCHAR(200) DEFAULT '',
            color VARCHAR(200) DEFAULT '',
            material VARCHAR(500) DEFAULT '',
            size VARCHAR(500) DEFAULT '',
            description_text TEXT DEFAULT '',
            detail_content_text TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_product_entry_translations_product_language UNIQUE (product_entry_id, language)
        )
    """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_product_entry_translations_product_entry_id "
            "ON product_entry_translations(product_entry_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_product_entry_translations_language "
            "ON product_entry_translations(language)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_product_entries_primary_category ON product_entries(primary_category)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_product_entries_normalized_brand ON product_entries(normalized_brand)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_product_entries_normalized_space ON product_entries(normalized_space)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_product_entries_normalized_style ON product_entries(normalized_style)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_product_entries_normalized_color ON product_entries(normalized_color)"
        )
    )
    conn.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS llm_call_metrics (
            id SERIAL PRIMARY KEY,
            operation VARCHAR(100) DEFAULT '',
            provider VARCHAR(100) DEFAULT '',
            model VARCHAR(200) DEFAULT '',
            duration_ms INTEGER,
            success BOOLEAN DEFAULT TRUE,
            error_type VARCHAR(200) DEFAULT '',
            error_message TEXT DEFAULT '',
            conversation_id INTEGER REFERENCES conversations(id),
            turn_metric_id INTEGER REFERENCES conversation_turn_metrics(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_llm_call_metrics_operation ON llm_call_metrics(operation)"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_llm_call_metrics_success ON llm_call_metrics(success)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_llm_call_metrics_conversation_id ON llm_call_metrics(conversation_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_llm_call_metrics_turn_metric_id ON llm_call_metrics(turn_metric_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_llm_call_metrics_created_at ON llm_call_metrics(created_at)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_turn_step_metrics_stage_started "
            "ON conversation_turn_step_metrics(stage_key, started_at)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_turn_metrics_intent_started "
            "ON conversation_turn_metrics(primary_intent, started_at)"
        )
    )
    conn.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS observability_alerts (
            id SERIAL PRIMARY KEY,
            severity VARCHAR(50) DEFAULT 'warning',
            metric_key VARCHAR(100) DEFAULT '',
            title VARCHAR(500) DEFAULT '',
            message TEXT DEFAULT '',
            observed_value FLOAT DEFAULT 0,
            threshold_value FLOAT DEFAULT 0,
            window_start TIMESTAMP NOT NULL,
            window_end TIMESTAMP NOT NULL,
            status VARCHAR(50) DEFAULT 'open',
            dedupe_key VARCHAR(500) NOT NULL UNIQUE,
            sample_conversation_ids_json TEXT DEFAULT '[]',
            sample_count INTEGER DEFAULT 0,
            sent_at TIMESTAMP,
            acknowledged_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
        )
    )
    for column, ddl in [
        (
            "sample_conversation_ids_json",
            "ALTER TABLE observability_alerts ADD COLUMN sample_conversation_ids_json TEXT DEFAULT '[]'",
        ),
        (
            "sample_count",
            "ALTER TABLE observability_alerts ADD COLUMN sample_count INTEGER DEFAULT 0",
        ),
    ]:
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'observability_alerts' AND column_name = :column"
            ),
            {"column": column},
        )
        if result.fetchone() is None:
            logger.info(f"Running migration: adding observability_alerts.{column}")
            conn.execute(text(ddl))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_observability_alerts_severity ON observability_alerts(severity)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_observability_alerts_metric_key ON observability_alerts(metric_key)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_observability_alerts_status ON observability_alerts(status)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_observability_alerts_window_start ON observability_alerts(window_start)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_observability_alerts_window_end ON observability_alerts(window_end)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_observability_alerts_dedupe_key ON observability_alerts(dedupe_key)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_observability_alerts_created_at ON observability_alerts(created_at)"
        )
    )
    conn.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS background_jobs (
            id SERIAL PRIMARY KEY,
            job_type VARCHAR(100) NOT NULL,
            entity_type VARCHAR(100) DEFAULT '',
            entity_id INTEGER,
            dedupe_key VARCHAR(500) NOT NULL UNIQUE,
            payload_json TEXT DEFAULT '{}',
            status VARCHAR(50) DEFAULT 'queued',
            run_after TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 1,
            locked_by VARCHAR(200) DEFAULT '',
            locked_at TIMESTAMP,
            last_error TEXT DEFAULT '',
            finished_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_background_jobs_job_type ON background_jobs(job_type)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_entity_type ON background_jobs(entity_type)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_entity_id ON background_jobs(entity_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_dedupe_key ON background_jobs(dedupe_key)"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_background_jobs_status ON background_jobs(status)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_run_after ON background_jobs(run_after)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_locked_by ON background_jobs(locked_by)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_locked_at ON background_jobs(locked_at)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_finished_at ON background_jobs(finished_at)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_created_at ON background_jobs(created_at)"
        )
    )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_run_migrations)
