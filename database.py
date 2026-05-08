import os
import json
import logging
from typing import Optional, Any

import asyncpg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     BIGINT PRIMARY KEY,
                name        TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id     BIGINT,
                key         TEXT,
                value       JSONB,
                updated_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, key)
            )
        """)
    logger.info("DB tables ready")


async def get_user(user_id: int, name: str = "") -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id = $1", user_id
        )
        if not row:
            await conn.execute(
                "INSERT INTO users (user_id, name) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                user_id, name
            )
            return {"user_id": user_id, "name": name}
        return dict(row)


async def get_all_users() -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [r["user_id"] for r in rows]


async def save_user_data(user_id: int, key: str, value: Any):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_data (user_id, key, value, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW())
            ON CONFLICT (user_id, key)
            DO UPDATE SET value = $3::jsonb, updated_at = NOW()
        """, user_id, key, json.dumps(value))


async def get_user_data(user_id: int, key: str) -> Optional[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if key == "all":
            rows = await conn.fetch(
                "SELECT key, value FROM user_data WHERE user_id = $1", user_id
            )
            return {r["key"]: json.loads(r["value"]) for r in rows}
        else:
            row = await conn.fetchrow(
                "SELECT value FROM user_data WHERE user_id = $1 AND key = $2",
                user_id, key
            )
            return json.loads(row["value"]) if row else None
