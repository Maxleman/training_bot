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

from database import init_db, get_user, save_user_data, get_user_data, save_chat_message, get_chat_history, clear_chat_history, get_user_context

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

# Shift schedule for May 2026
DAY_SHIFTS = {3,10,11,12,15,16,17,21,22,28}
NIGHT_SHIFTS = {5,7,8,19,29,30,31}

def get_minsk_now():
    """Get current time in Minsk (UTC+3)"""
    from datetime import timezone, timedelta
    utc_now = datetime.now(timezone.utc)
    minsk = utc_now + timedelta(hours=3)
    return minsk

async def notify_all_users(text: str):
    """Send message to all registered users"""
    users = await database.get_all_users()
    for user_id in users:
        try:
            await send_message(user_id, text)
        except Exception as e:
            logger.error(f"Failed to notify {user_id}: {e}")

async def notify_after_day_shift():
    """21:30 Minsk — after day shift ends, if today is training day"""
    now = get_minsk_now()
    day = now.day
    if now.month != 5 or now.year != 2026:
        return
    if day not in DAY_SHIFTS:
        return  # Not a day shift today
    workout = TRAIN_DAYS.get(day)
    if not workout:
        return
    emoji = WORKOUT_EMOJI.get(workout, "💪")
    text = (
        f"{emoji} <b>Смена закончилась — время для себя!</b>\n\n"
        f"Сегодня: <b>{workout}</b>\n\n"
        f"План:\n"
        f"• Поешь нормально (белок + углеводы)\n"
        f"• Подожди 1–1.5 часа\n"
        f"• Тренировка — 45–60 минут\n"
        f"• Гейнер сразу после 🥤\n\n"
        f"Открой приложение 👇"
    )
    await notify_all_users(text)

async def notify_before_night_shift():
    """13:00 Minsk — before night shift, if today is training day"""
    now = get_minsk_now()
    day = now.day
    if now.month != 5 or now.year != 2026:
        return
    if day not in NIGHT_SHIFTS:
        return  # Not a night shift today
    workout = TRAIN_DAYS.get(day)
    if not workout:
        return
    emoji = WORKOUT_EMOJI.get(workout, "💪")
    text = (
        f"{emoji} <b>До ночной смены 8 часов!</b>\n\n"
        f"Успей потренироваться: <b>{workout}</b>\n\n"
        f"Лучшее время — прямо сейчас или в 15:00–16:00.\n"
        f"После тренировки плотно поешь — смена длинная 🌙\n\n"
        f"Открой приложение 👇"
    )
    await notify_all_users(text)

async def notify_rest_day():
    """10:00 Minsk — rest or free day with training"""
    now = get_minsk_now()
    day = now.day
    if now.month != 5 or now.year != 2026:
        return
    if day in DAY_SHIFTS or day in NIGHT_SHIFTS:
        return  # Has a shift, other notifications handle it
    workout = TRAIN_DAYS.get(day)
    if not workout:
        return
    emoji = WORKOUT_EMOJI.get(workout, "💪")
    text = (
        f"☀️ <b>Доброе утро, Максим!</b>\n\n"
        f"Сегодня выходной и день тренировки.\n"
        f"{emoji} <b>{workout}</b>\n\n"
        f"Лучшее время: 11:00–13:00 — тело уже проснулось, \n"
        f"но ещё не устало. Поешь за 1.5 часа до.\n\n"
        f"Открой приложение 👇"
    )
    await notify_all_users(text)

async def notify_evening():
    """21:30 Minsk — evening reminders for everyone"""
    now = get_minsk_now()
    day = now.day
    if now.month != 5 or now.year != 2026:
        return
    # Only on non-night-shift days (night shift workers are at work)
    if day in NIGHT_SHIFTS:
        return
    text = (
        f"🌙 <b>Вечернее напоминание</b>\n\n"
        f"• Творог 200г перед сном — медленный белок для мышц ночью\n"
        f"• Выпил 2.5л воды сегодня? 💧\n"
        f"• Записал замеры на этой неделе? 📏\n\n"
        f"Спокойной ночи 😴"
    )
    await notify_all_users(text)

async def send_daily_notification():
    """Legacy — kept for compatibility"""
    pass

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

    # Smart notifications based on shift schedule
    # Day shift (9:00-21:00): notify at 21:30 after work
    scheduler.add_job(
        notify_after_day_shift,
        CronTrigger(hour=18, minute=30, timezone="UTC"),  # 21:30 Minsk
        id="notify_day_shift"
    )
    # Night shift (21:00-9:00): notify at 13:00 before shift
    scheduler.add_job(
        notify_before_night_shift,
        CronTrigger(hour=10, minute=0, timezone="UTC"),  # 13:00 Minsk
        id="notify_night_shift"
    )
    # Rest day: notify at 10:00
    scheduler.add_job(
        notify_rest_day,
        CronTrigger(hour=7, minute=0, timezone="UTC"),  # 10:00 Minsk
        id="notify_rest_day"
    )
    # Evening reminder: творог before sleep at 21:30
    scheduler.add_job(
        notify_evening,
        CronTrigger(hour=18, minute=30, timezone="UTC"),  # 21:30 Minsk
        id="notify_evening"
    )
    scheduler.start()
    logger.info("Scheduler started with smart notifications")

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
            f"🔔 Умные уведомления по графику смен\n"
            f"🤖 ИИ-тренер на базе Groq Llama 3.3\n\n"
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

    elif text == "/schedule":
        day = datetime.now().day
        shift_today = "☀️ Дневная (9:00–21:00)" if day in DAY_SHIFTS else "🌙 Ночная (21:00–9:00)" if day in NIGHT_SHIFTS else "🏠 Выходной"
        workout_today = TRAIN_DAYS.get(day)
        notify_time = "21:30" if day in DAY_SHIFTS else "13:00" if day in NIGHT_SHIFTS else "10:00"
        await send_message(
            chat_id,
            f"📅 <b>Сегодня, {day} мая:</b>\n\n"
            f"Смена: {shift_today}\n"
            f"Тренировка: {'🏋 ' + workout_today if workout_today else '🛌 Нет'} \n"
            f"Уведомление: {'в ' + notify_time if workout_today else 'вечернее в 21:30'}\n\n"
            f"Уведомления приходят автоматически по расписанию смен."
        )

    elif text == "/notify":
        await send_message(
            chat_id,
            "🔔 <b>Умные уведомления активны!</b>\n\n"
            "Время зависит от твоей смены:\n"
            "☀️ Дневная → уведомление в <b>21:30</b> (после работы)\n"
            "🌙 Ночная → уведомление в <b>13:00</b> (до смены)\n"
            "🏠 Выходной → уведомление в <b>10:00</b>\n"
            "🌙 Вечером в 21:30 — напоминание про творог и воду\n\n"
            "Команды:\n"
            "/today — что сегодня\n"
            "/schedule — расписание на сегодня\n"
            "/ai — ИИ-тренер\n"
            "/stats — статистика\n"
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

BASE_SYSTEM_PROMPT = """Ты персональный тренер и диетолог Максима. Вот его данные:

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


async def build_system_prompt(user_id: int = None) -> str:
    """Build personalized system prompt with user's actual data"""
    base = BASE_SYSTEM_PROMPT
    if not user_id:
        return base
    try:
        ctx = await get_user_context(user_id)
        extra = f"""

АКТУАЛЬНЫЕ ДАННЫЕ МАКСИМА (из приложения):
- Последний замер: {ctx['last_measure_date']}
- Вес: {ctx['weight']} кг
- Грудь: {ctx['chest']} см
- Талия: {ctx['waist']} см
- Бицепс: {ctx['bicep']} см
- Тренировок выполнено в мае: {ctx['done_trainings']} из 18

Используй эти данные когда отвечаешь на вопросы про прогресс."""
        return base + extra
    except:
        return base

@app.post("/api/ai-trainer")
async def ai_trainer(request: Request):
    if not GROQ_API_KEY:
        return JSONResponse({"error": "GROQ_API_KEY not configured"}, status_code=500)

    body = await request.json()
    message = body.get("message", "").strip()
    user_id = body.get("user_id")

    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    uid = int(user_id) if user_id else None

    # 1. Load existing history BEFORE saving new message
    if uid:
        db_history = await get_chat_history(uid)
        system_prompt = await build_system_prompt(uid)
    else:
        db_history = body.get("history", [])
        system_prompt = await build_system_prompt()

    # 2. Build messages: system + history + NEW message
    messages = [{"role": "system", "content": system_prompt}]
    for h in db_history[-14:]:  # last 14 for context
        role = "user" if h.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": h.get("text", "")})
    messages.append({"role": "user", "content": message})

    # 3. Call Groq
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 500,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GROQ_URL, json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        )
        data = resp.json()

    if resp.status_code != 200:
        logger.error(f"Groq error: {data}")
        return JSONResponse({"error": "AI error", "detail": str(data)}, status_code=500)

    reply = data["choices"][0]["message"]["content"]

    # 4. Save BOTH messages to DB after successful response
    if uid:
        await save_chat_message(uid, "user", message)
        await save_chat_message(uid, "assistant", reply)

    return {"reply": reply}


@app.delete("/api/ai-trainer/{user_id}/history")
async def clear_ai_history(user_id: int):
    """Clear chat history for user"""
    await clear_chat_history(user_id)
    return {"ok": True}


@app.get("/api/ai-trainer/{user_id}/history")
async def get_ai_history(user_id: int):
    """Get chat history for user"""
    history = await get_chat_history(user_id)
    return {"history": history}

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
