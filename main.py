import os
import asyncio
import logging
from datetime import datetime, time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import init_db, get_user, save_user_data, get_user_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # your Railway URL
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

scheduler = AsyncIOScheduler(timezone="Europe/Minsk")

# Training schedule for May 2026
TRAIN_DAYS = {
    1: "Грудь/Трицепс", 2: "Спина/Бицепс",
    3: "Плечи/Пресс", 6: "Ноги/Плечи",
    10: "Грудь/Трицепс", 11: "Спина/Бицепс",
    13: "Плечи/Пресс", 14: "Ноги/Плечи",
    15: "Грудь/Трицепс", 17: "Спина/Бицепс",
    18: "Плечи/Пресс", 20: "Ноги/Плечи",
    21: "Грудь/Трицепс", 22: "Спина/Бицепс",
    24: "Плечи/Пресс", 25: "Ноги/Плечи",
    27: "Грудь/Трицепс", 28: "Спина/Бицепс",
}

WORKOUT_EMOJI = {
    "Грудь/Трицепс": "💪",
    "Спина/Бицепс": "🏋",
    "Плечи/Пресс": "🎯",
    "Ноги/Плечи": "🦵",
}

async def send_message(chat_id: int, text: str, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)

async def send_daily_notification():
    """Send workout reminder to all users at 9:00 Minsk time"""
    now = datetime.now()
    day = now.day
    month = now.month
    year = now.year

    if month != 5 or year != 2026:
        return

    workout = TRAIN_DAYS.get(day)
    if not workout:
        return

    emoji = WORKOUT_EMOJI.get(workout, "💪")
    text = (
        f"{emoji} <b>Сегодня день тренировки!</b>\n\n"
        f"📅 {day} мая — <b>{workout}</b>\n\n"
        f"Не забудь:\n"
        f"• Поешь за 1.5 часа до тренировки\n"
        f"• Гейнер после\n"
        f"• Вода минимум 2.5л\n\n"
        f"Открой приложение и отмечай подходы 👇"
    )

    # Get all users from DB and notify
    import database
    users = await database.get_all_users()
    for user_id in users:
        try:
            await send_message(user_id, text)
        except Exception as e:
            logger.error(f"Failed to notify {user_id}: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    logger.info("Database initialized")

    # Set webhook
    if BOT_TOKEN and WEBHOOK_URL:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{TELEGRAM_API}/setWebhook",
                json={"url": f"{WEBHOOK_URL}/webhook"}
            )
            logger.info(f"Webhook set: {resp.json()}")

    # Schedule daily notification at 9:00 Minsk (UTC+3)
    scheduler.add_job(
        send_daily_notification,
        CronTrigger(hour=6, minute=0, timezone="UTC"),  # 9:00 Minsk = 6:00 UTC
        id="daily_notify"
    )
    scheduler.start()
    logger.info("Scheduler started")

    yield

    # Shutdown
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── TELEGRAM WEBHOOK ───────────────────────────────────────────
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    logger.info(f"Webhook: {data}")

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    user = message.get("from", {})
    user_id = user.get("id")

    if not chat_id:
        return {"ok": True}

    # Register user
    await get_user(user_id, user.get("first_name", "Максим"))

    app_url = f"{WEBHOOK_URL}/app"

    if text == "/start":
        keyboard = {
            "inline_keyboard": [[
                {
                    "text": "🏋 Открыть приложение",
                    "web_app": {"url": app_url}
                }
            ]]
        }
        await send_message(
            chat_id,
            f"👋 Привет, <b>{user.get('first_name', 'Максим')}</b>!\n\n"
            f"Твой персональный тренировочный план на май 2026.\n\n"
            f"📅 <b>18 тренировок</b> под твой сменный график\n"
            f"🍽 Меню с рецептами и ценами в BYN\n"
            f"💧 Трекер воды и калорий\n"
            f"📈 Прогресс и замеры\n"
            f"🔔 Уведомления в дни тренировок в 9:00\n\n"
            f"Нажми кнопку ниже 👇",
            reply_markup=keyboard
        )

    elif text == "/today":
        day = datetime.now().day
        workout = TRAIN_DAYS.get(day)
        if workout:
            emoji = WORKOUT_EMOJI.get(workout, "💪")
            await send_message(chat_id, f"{emoji} Сегодня: <b>{workout}</b>\n\nОткрой приложение чтобы начать тренировку!")
        else:
            await send_message(chat_id, "🛌 Сегодня день отдыха. Восстанавливайся и ешь по плану!")

    elif text == "/notify":
        await send_message(
            chat_id,
            "🔔 <b>Уведомления включены!</b>\n\n"
            "Каждый день тренировки в <b>9:00</b> по Минску я пришлю напоминание.\n\n"
            "Команды:\n"
            "/today — что сегодня\n"
            "/stats — твоя статистика\n"
            "/start — главное меню"
        )

    elif text == "/stats":
        user_data = await get_user_data(user_id, "stats")
        done = user_data.get("done_trainings", 0) if user_data else 0
        water = user_data.get("total_water_ml", 0) if user_data else 0
        await send_message(
            chat_id,
            f"📊 <b>Твоя статистика за май:</b>\n\n"
            f"✅ Тренировок выполнено: <b>{done}</b> из 18\n"
            f"💧 Воды выпито всего: <b>{water // 1000}л {water % 1000}мл</b>\n\n"
            f"Открой приложение для подробной статистики 👇"
        )

    return {"ok": True}

# ─── API ENDPOINTS ───────────────────────────────────────────────
@app.get("/api/user/{user_id}")
async def api_get_user(user_id: int):
    data = await get_user_data(user_id, "all")
    return JSONResponse(data or {})

@app.post("/api/user/{user_id}/data")
async def api_save_data(user_id: int, request: Request):
    body = await request.json()
    key = body.get("key")
    value = body.get("value")
    if not key:
        raise HTTPException(400, "key required")
    await save_user_data(user_id, key, value)
    return {"ok": True}

@app.get("/api/schedule")
async def api_schedule():
    return {"train_days": TRAIN_DAYS}

# ─── SERVE MINI APP ──────────────────────────────────────────────
@app.get("/app")
async def serve_app():
    return FileResponse("static/index.html")

@app.get("/")
async def root():
    return {"status": "ok", "service": "Training Bot API"}

app.mount("/static", StaticFiles(directory="static"), name="static")
