"""
Слой доступа к PostgreSQL.

Таблицы:
- users: телеграм-пользователи, их выбранный язык
- message_map: связка "сообщение в чате админа" -> "исходное сообщение пользователя",
  нужна чтобы реплай админа долетал до нужного пользователя.

Все данные переживают перезапуск контейнера, т.к. хранятся в Postgres
(который в docker-compose поднят с отдельным volume).
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

logger = logging.getLogger("support-bot.db")

_pool: Optional[asyncpg.Pool] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    language TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS message_map (
    admin_message_id BIGINT PRIMARY KEY,
    user_chat_id BIGINT NOT NULL,
    user_message_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_message_map_user_chat_id ON message_map (user_chat_id);
"""


async def init_pool(dsn: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)
    logger.info("Database pool initialized and schema ensured")


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()
        logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_pool() first.")
    return _pool


async def upsert_user(
    chat_id: int,
    username: Optional[str],
    first_name: Optional[str],
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO users (chat_id, username, first_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (chat_id) DO UPDATE
        SET username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            updated_at = now()
        """,
        chat_id,
        username,
        first_name,
    )


async def set_user_language(chat_id: int, language: str) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO users (chat_id, language)
        VALUES ($1, $2)
        ON CONFLICT (chat_id) DO UPDATE
        SET language = EXCLUDED.language,
            updated_at = now()
        """,
        chat_id,
        language,
    )


async def get_user_language(chat_id: int) -> Optional[str]:
    pool = get_pool()
    row = await pool.fetchrow("SELECT language FROM users WHERE chat_id = $1", chat_id)
    if row is None:
        return None
    return row["language"]


async def save_message_mapping(admin_message_id: int, user_chat_id: int, user_message_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO message_map (admin_message_id, user_chat_id, user_message_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (admin_message_id) DO UPDATE
        SET user_chat_id = EXCLUDED.user_chat_id,
            user_message_id = EXCLUDED.user_message_id
        """,
        admin_message_id,
        user_chat_id,
        user_message_id,
    )


async def get_message_mapping(admin_message_id: int) -> Optional[tuple[int, int]]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT user_chat_id, user_message_id FROM message_map WHERE admin_message_id = $1",
        admin_message_id,
    )
    if row is None:
        return None
    return int(row["user_chat_id"]), int(row["user_message_id"])


async def get_user_stats() -> dict:
    pool = get_pool()
    total = await pool.fetchval("SELECT COUNT(*) FROM users")
    ru_count = await pool.fetchval("SELECT COUNT(*) FROM users WHERE language = 'ru'")
    tk_count = await pool.fetchval("SELECT COUNT(*) FROM users WHERE language = 'tk'")
    return {"total_users": total or 0, "ru_count": ru_count or 0, "tk_count": tk_count or 0}
