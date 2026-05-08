import os
import json
import logging
from typing import Optional, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

logger = logging.getLogger(__name__)
_raw_url = os.getenv("DATABASE_URL", "")
# Render gives postgres://, psycopg2 needs postgresql://
DATABASE_URL = _raw_url.replace("postgres://", "postgresql://", 1)

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

async def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     BIGINT PRIMARY KEY,
                    name        TEXT,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_data (
                    user_id     BIGINT,
                    key         TEXT,
                    value       JSONB,
                    updated_at  TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, key)
                )
            """)
        conn.commit()
    logger.info("DB tables ready")

async def get_user(user_id: int, name: str = "") -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                cur.execute(
                    "INSERT INTO users (user_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (user_id, name)
                )
                conn.commit()
                return {"user_id": user_id, "name": name}
            return dict(row)

async def get_all_users() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [r["user_id"] for r in cur.fetchall()]

async def save_user_data(user_id: int, key: str, value: Any):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_data (user_id, key, value, updated_at)
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (user_id, key)
                DO UPDATE SET value = %s::jsonb, updated_at = NOW()
            """, (user_id, key, json.dumps(value), json.dumps(value)))
        conn.commit()

async def get_user_data(user_id: int, key: str) -> Optional[Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if key == "all":
                cur.execute(
                    "SELECT key, value FROM user_data WHERE user_id = %s", (user_id,)
                )
                return {r["key"]: r["value"] for r in cur.fetchall()}
            else:
                cur.execute(
                    "SELECT value FROM user_data WHERE user_id = %s AND key = %s",
                    (user_id, key)
                )
                row = cur.fetchone()
                return row["value"] if row else None
