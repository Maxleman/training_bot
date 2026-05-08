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
    try:
        await init_db()
        logger.info("Database initialized OK")
    except Exception as e:
        logger.error(f"DB init failed: {e}")
        logger.error(f"DATABASE_URL set: {bool(os.getenv('DATABASE_URL'))}")
        raise

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
            f"🔔 Уведомления в дни тренировок в 9:00\n"
            f"🤖 ИИ-тренер — отвечает на любые вопросы\n\n"
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
            "/ai — ИИ-тренер (задай любой вопрос)\n"
            "/stats — твоя статистика\n"
            "/start — главное меню"
        )

    elif text.startswith("/ai ") or text.startswith("/ask "):
        question = text.split(" ", 1)[1] if " " in text else ""
        if question:
            await send_message(chat_id, "🤔 Думаю...")
            await handle_ai_message(chat_id, question)
        else:
            await send_message(chat_id, "Напиши вопрос после команды, например:\n/ai чем заменить подтягивания?")

    elif text == "/ai":
        await send_message(
            chat_id,
            "🤖 <b>ИИ-тренер</b>\n\n"
            "Задай любой вопрос про тренировки и питание:\n"
            "/ai чем заменить подтягивания?\n"
            "/ai что съесть перед ночной сменой?\n"
            "/ai болит запястье — что делать?\n"
            "/ai сколько белка мне нужно?\n\n"
            "Или открой приложение — там есть чат с тренером 👇"
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


import re

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """Ты персональный тренер и диетолог Максима. Вот его данные:

ПРОФИЛЬ:
- Имя: Максим
- Возраст: ~20-25 лет  
- Вес: 58-59 кг, Рост: 176-178 см
- Цель: набор мышечной массы, рельеф (грудь, руки, пресс, спина)
- График: сменная работа (дневные и ночные смены)
- Тренировки: дома (отжимания, подтягивания, рюкзак с книгами)
- Скоро переходит в тренажёрный зал

ПЛАН ТРЕНИРОВОК (май 2026, дома):
- Грудь/Трицепс: отжимания классические 4×макс, узкий хват 3×10-12, с ногами на стуле 3×10, обратные от стула 3×12, планка 3×60с
- Спина/Бицепс: подтягивания 4×макс, тяга рюкзака 4×12, сгибания на бицепс 4×12, гиперэкстензия 3×15, молотки 3×12
- Плечи/Пресс: жим рюкзака 4×12, отжимания пайк 3×12, скручивания 3×20, подъём ног 3×15, боковая планка 3×30с, велосипед 3×20
- Ноги/Плечи: приседания с рюкзаком 4×15, выпады 3×12, подъёмы на носки 3×20, прыжки squat 3×12

ПИТАНИЕ:
- Калории: ~2800 ккал/день (профицит для набора массы)
- Белок: 120-130г, Жиры: 75-85г, Углеводы: 380-420г
- Есть гейнер (принимает после тренировки)
- Основные продукты: гречка, рис, курица, говядина, рыба, творог, яйца, овсянка

ПРАВИЛА ОТВЕТОВ:
- Отвечай коротко и по делу (3-6 предложений максимум)
- Используй эмодзи умеренно
- Давай конкретные советы, не общие фразы
- Учитывай его сменный график при советах по питанию и восстановлению
- Если спрашивает про упражнение — дай конкретную замену из его арсенала
- Отвечай на русском языке
- Обращайся по имени иногда, но не в каждом сообщении"""

@app.post("/api/ai-trainer")
async def ai_trainer(request: Request):
    if not GROQ_API_KEY:
        return JSONResponse({"error": "GROQ_API_KEY not configured"}, status_code=500)

    body = await request.json()
    message = body.get("message", "").strip()
    history = body.get("history", [])

    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    # Build messages for Groq (OpenAI format)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-6:]:
        role = "user" if h.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": h.get("text", "")})
    messages.append({"role": "user", "content": message})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 400,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GROQ_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
        )
        data = resp.json()

    if resp.status_code != 200:
        logger.error(f"Groq error: {data}")
        return JSONResponse({"error": "AI error", "detail": str(data)}, status_code=500)

    text = data["choices"][0]["message"]["content"]
    return {"reply": text}

# Handle AI questions via bot commands too
async def handle_ai_message(chat_id: int, user_message: str):
    """Process AI trainer request from Telegram bot"""
    if not GROQ_API_KEY:
        await send_message(chat_id, "⚠️ ИИ-тренер не настроен. Добавь GROQ_API_KEY в переменные.")
        return

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 400,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GROQ_URL, json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        )
        data = resp.json()

    if resp.status_code == 200:
        reply = data["choices"][0]["message"]["content"]
        await send_message(chat_id, f"🤖 {reply}")
    else:
        await send_message(chat_id, f"⚠️ Ошибка ИИ: {data.get('error', {}).get('message', 'неизвестная ошибка')}")


@app.get("/test-ai")
async def test_ai():
    """Test Groq API connection"""
    if not GROQ_API_KEY:
        return {"error": "GROQ_API_KEY not set"}

    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": "скажи привет одним словом"}],
        "max_tokens": 20
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GROQ_URL, json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        )
        data = resp.json()

    return {
        "status_code": resp.status_code,
        "model": GROQ_MODEL,
        "key_prefix": GROQ_API_KEY[:8] + "...",
        "response": data
    }


@app.get("/setup")
async def setup_webhook():
    """Call this once to register the webhook with Telegram"""
    if not BOT_TOKEN or not WEBHOOK_URL:
        return {"error": "BOT_TOKEN or WEBHOOK_URL not set in environment variables"}
    async with httpx.AsyncClient() as client:
        # Delete old webhook first
        await client.post(f"{TELEGRAM_API}/deleteWebhook")
        # Set new webhook
        resp = await client.post(
            f"{TELEGRAM_API}/setWebhook",
            json={
                "url": f"{WEBHOOK_URL}/webhook",
                "allowed_updates": ["message", "callback_query"]
            }
        )
        data = resp.json()
        return {
            "webhook_set": data,
            "webhook_url": f"{WEBHOOK_URL}/webhook",
            "bot_token": "set" if BOT_TOKEN else "MISSING",
        }

@app.get("/status")
async def status():
    """Check if everything is configured"""
    result = {
        "server": "ok",
        "bot_token": "set" if BOT_TOKEN else "MISSING - add BOT_TOKEN in Railway Variables",
        "webhook_url": WEBHOOK_URL or "MISSING - add WEBHOOK_URL in Railway Variables",
    }
    if BOT_TOKEN:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{TELEGRAM_API}/getWebhookInfo")
            wh = r.json().get("result", {})
            result["webhook_registered"] = wh.get("url", "not set")
            result["pending_updates"] = wh.get("pending_update_count", 0)
    return result

app.mount("/static", StaticFiles(directory="static"), name="static")
