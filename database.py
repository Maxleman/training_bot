import os
import json
import logging
from typing import Optional, Any
import databases
import sqlalchemy

logger = logging.getLogger(__name__)

_raw_url = os.getenv("DATABASE_URL", "")
DATABASE_URL = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1).replace("postgresql://", "postgresql+asyncpg://", 1)

database = databases.Database(DATABASE_URL)

metadata = sqlalchemy.MetaData()

users_table = sqlalchemy.Table(
    "users", metadata,
    sqlalchemy.Column("user_id", sqlalchemy.BigInteger, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.Text),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime(timezone=True), server_default=sqlalchemy.func.now()),
)

user_data_table = sqlalchemy.Table(
    "user_data", metadata,
    sqlalchemy.Column("user_id", sqlalchemy.BigInteger),
    sqlalchemy.Column("key", sqlalchemy.Text),
    sqlalchemy.Column("value", sqlalchemy.Text),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime(timezone=True), server_default=sqlalchemy.func.now()),
    sqlalchemy.PrimaryKeyConstraint("user_id", "key"),
)

async def init_db():
    await database.connect()
    # Create tables using raw SQL
    await database.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     BIGINT PRIMARY KEY,
            name        TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await database.execute("""
        CREATE TABLE IF NOT EXISTS user_data (
            user_id     BIGINT,
            key         TEXT,
            value       TEXT,
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, key)
        )
    """)
    logger.info("DB tables ready")

async def get_user(user_id: int, name: str = "") -> dict:
    row = await database.fetch_one(
        "SELECT * FROM users WHERE user_id = :uid", {"uid": user_id}
    )
    if not row:
        await database.execute(
            "INSERT INTO users (user_id, name) VALUES (:uid, :name) ON CONFLICT DO NOTHING",
            {"uid": user_id, "name": name}
        )
        return {"user_id": user_id, "name": name}
    return dict(row)

async def get_all_users() -> list:
    rows = await database.fetch_all("SELECT user_id FROM users")
    return [r["user_id"] for r in rows]

async def save_user_data(user_id: int, key: str, value: Any):
    val_str = json.dumps(value)
    await database.execute("""
        INSERT INTO user_data (user_id, key, value, updated_at)
        VALUES (:uid, :key, :val, NOW())
        ON CONFLICT (user_id, key)
        DO UPDATE SET value = :val, updated_at = NOW()
    """, {"uid": user_id, "key": key, "val": val_str})

async def get_user_data(user_id: int, key: str) -> Optional[Any]:
    if key == "all":
        rows = await database.fetch_all(
            "SELECT key, value FROM user_data WHERE user_id = :uid", {"uid": user_id}
        )
        return {r["key"]: json.loads(r["value"]) for r in rows}
    else:
        row = await database.fetch_one(
            "SELECT value FROM user_data WHERE user_id = :uid AND key = :key",
            {"uid": user_id, "key": key}
        )
        return json.loads(row["value"]) if row else None


async def save_chat_message(user_id: int, role: str, text: str):
    """Save a single chat message to history"""
    key = "chat_history"
    history = await get_user_data(user_id, key) or []
    history.append({
        "role": role,
        "text": text,
        "ts": __import__('datetime').datetime.now().isoformat()
    })
    # Keep last 40 messages
    if len(history) > 40:
        history = history[-40:]
    await save_user_data(user_id, key, history)

async def get_chat_history(user_id: int) -> list:
    """Get chat history for user"""
    return await get_user_data(user_id, "chat_history") or []

async def clear_chat_history(user_id: int):
    """Clear chat history"""
    await save_user_data(user_id, "chat_history", [])

async def get_user_context(user_id: int) -> dict:
    """Get all user data for AI context"""
    all_data = await get_user_data(user_id, "all") or {}
    measures = all_data.get("measures", [])
    last = measures[0] if measures else {}
    done = all_data.get("doneTrains", {})
    return {
        "weight": last.get("weight", "не указан"),
        "chest": last.get("chest", "не указан"),
        "waist": last.get("waist", "не указан"),
        "bicep": last.get("bicep", "не указан"),
        "done_trainings": len(done),
        "last_measure_date": last.get("date", "нет замеров"),
    }
