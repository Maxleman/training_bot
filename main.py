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

BASE_SYSTEM_PROMPT = """Ты — персональный тренер, диетолог и нутрициолог Максима. Ты знаешь его досконально.

ПРОФИЛЬ МАКСИМА:
- Возраст: ~20-25 лет, Вес: 58-59 кг, Рост: 176-178 см, ИМТ: ~18.5 (нижняя граница нормы)
- Цель: набор мышечной массы + рельеф (приоритет: грудь, руки, пресс, спина)
- Работает посменно: дневная 9:00-21:00 или ночная 21:00-9:00
- Тренируется дома с рюкзаком (10-15кг книг), отжимания, подтягивания
- Планирует перейти в тренажёрный зал
- Пьёт гейнер после тренировки
- Живёт в Минске, Беларусь

ПЛАН ТРЕНИРОВОК (дома):
• Грудь/Трицепс: отжимания 4×макс, узкий хват 3×10-12, с ногами на стуле 3×10, обратные от стула 3×12, планка 3×60с
• Спина/Бицепс: подтягивания 4×макс, тяга рюкзака 4×12, сгибания с рюкзаком 4×12, гиперэкстензия 3×15, молотки 3×12
• Плечи/Пресс: жим рюкзака 4×12, пайк 3×12, скручивания 3×20, подъём ног 3×15, боковая планка 3×30с, велосипед 3×20
• Ноги/Плечи: приседания с рюкзаком 4×15, выпады 3×12, носки 3×20, прыжки squat 3×12

ПИТАНИЕ:
- Цель: 2800 ккал/день (профицит ~300-400 ккал для набора)
- Макро: Белок 125г / Жиры 80г / Углеводы 400г
- Основа рациона: гречка, рис, курица, говядина, хек/минтай, творог 5%, яйца, овсянка, бананы
- Гейнер: сразу после тренировки на молоке

ПРАВИЛА ОТВЕТОВ (СТРОГО):
1. КОНКРЕТНОСТЬ: никогда не говори "ешь больше белка" — говори "добавь 150г куриной грудки к обеду, это +47г белка"
2. ЦИФРЫ: всегда давай конкретные граммы, повторы, время, калории
3. АЛЬТЕРНАТИВЫ: если спрашивает про замену — дай 2-3 конкретных варианта из его арсенала с подходами
4. УЧИТЫВАЙ КОНТЕКСТ: если знаешь его смену, сон, съеденное сегодня — учитывай в ответе
5. СТРУКТУРА для сложных вопросов: короткий вывод → конкретный план → почему это работает
6. ДЛИНА: простой вопрос = 2-4 предложения. Сложный = до 8 предложений с конкретикой
7. БЕЛАРУСЬ: знаешь местные продукты, цены, магазины (Евроопт, Виталюр, Гиппо, Корона)
8. ЯЗЫК: только русский, эмодзи умеренно (1-2 на ответ максимум)
9. НЕ ПОВТОРЯЙ вопрос пользователя в ответе
10. ЗАПРЕЩЕНО: "это зависит от...", "у каждого по-разному", "проконсультируйся с врачом" (только если реально опасно)

ЦЕНЫ В МИНСКЕ (актуальные, BYN):
- Куриная грудка: 9-11 BYN/кг (Евроопт, Виталюр)
- Говядина мякоть: 15-18 BYN/кг
- Хек/минтай: 7-9 BYN/кг
- Творог 5% 200г: 1.8-2.2 BYN
- Яйца С1 10шт: 3.0-3.5 BYN
- Гречка 800г: 2.5-3.0 BYN
- Рис 800г: 2.8-3.2 BYN
- Овсянка 500г: 1.5-2.0 BYN
- Молоко 1л: 1.4-1.7 BYN
- Бананы 1кг: 2.0-2.5 BYN
- Оливковое масло 500мл: 8-12 BYN
- Арахисовая паста 200г: 4-6 BYN
- Грецкие орехи 200г: 5-7 BYN"""


# ==================== AI TOOLS (Function Calling) ====================
AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_food_to_diary",
            "description": "Добавляет блюдо или продукт в дневник питания пользователя на сегодня с рассчитанным КБЖУ",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название блюда или продукта"},
                    "grams": {"type": "number", "description": "Количество в граммах"},
                    "kcal": {"type": "number", "description": "Калории на указанное количество"},
                    "protein": {"type": "number", "description": "Белки в граммах"},
                    "fat": {"type": "number", "description": "Жиры в граммах"},
                    "carbs": {"type": "number", "description": "Углеводы в граммах"},
                    "meal_slot": {"type": "string", "description": "Приём пищи: breakfast, snack1, lunch, preworkout, postworkout, dinner, sleep"}
                },
                "required": ["name", "grams", "kcal", "protein", "fat", "carbs"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_kbzhu",
            "description": "Рассчитывает КБЖУ для блюда по ингредиентам и возвращает результат",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "Название блюда"},
                    "ingredients": {
                        "type": "array",
                        "description": "Список ингредиентов",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "grams": {"type": "number"},
                                "kcal_per_100g": {"type": "number"},
                                "protein_per_100g": {"type": "number"},
                                "fat_per_100g": {"type": "number"},
                                "carbs_per_100g": {"type": "number"}
                            },
                            "required": ["name", "grams", "kcal_per_100g"]
                        }
                    }
                },
                "required": ["dish_name", "ingredients"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_product_price",
            "description": "Обновляет цену продукта в базе цен Минска",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "Название продукта"},
                    "price_byn": {"type": "number", "description": "Новая цена в BYN"},
                    "unit": {"type": "string", "description": "Единица измерения: кг, шт, л, 200г и т.д."},
                    "store": {"type": "string", "description": "Магазин: Евроопт, Виталюр, Гиппо, Корона или другой"}
                },
                "required": ["product_name", "price_byn", "unit"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_shopping_list",
            "description": "Добавляет продукт в список покупок",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "Название продукта"},
                    "quantity": {"type": "string", "description": "Количество (500г, 1кг, 2шт и т.д.)"},
                    "price_byn": {"type": "number", "description": "Примерная цена в BYN"},
                    "category": {"type": "string", "description": "Категория: Мясо и рыба, Молочное, Крупы и макароны, Овощи и фрукты, Прочее"}
                },
                "required": ["product_name", "quantity"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_product_kbzhu",
            "description": "Ищет КБЖУ продукта или блюда по названию и возвращает данные на 100г. Используй когда пользователь спрашивает КБЖУ неизвестного продукта или хочет добавить что-то в дневник/меню.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "Название продукта или блюда"},
                    "grams": {"type": "number", "description": "Количество в граммах которое нужно посчитать"},
                    "kcal_per_100g": {"type": "number", "description": "Калории на 100г (используй свои знания)"},
                    "protein_per_100g": {"type": "number", "description": "Белки на 100г"},
                    "fat_per_100g": {"type": "number", "description": "Жиры на 100г"},
                    "carbs_per_100g": {"type": "number", "description": "Углеводы на 100г"},
                    "add_to_diary": {"type": "boolean", "description": "true если нужно сразу добавить в дневник"}
                },
                "required": ["product_name", "grams", "kcal_per_100g", "protein_per_100g", "fat_per_100g", "carbs_per_100g"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_menu",
            "description": "Добавляет блюдо в конструктор меню на конкретный день",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer", "description": "День мая (1-31)"},
                    "meal_slot": {"type": "string", "description": "Слот: breakfast, snack1, lunch, preworkout, postworkout, dinner, sleep"},
                    "dish_name": {"type": "string", "description": "Название блюда"},
                    "kcal": {"type": "number", "description": "Калории"},
                    "protein": {"type": "number", "description": "Белки г"},
                    "fat": {"type": "number", "description": "Жиры г"},
                    "carbs": {"type": "number", "description": "Углеводы г"}
                },
                "required": ["meal_slot", "dish_name", "kcal", "protein", "fat", "carbs"]
            }
        }
    }
]

async def execute_tool(tool_name: str, args: dict, user_id: int = None) -> dict:
    """Execute a tool call and return result + UI action"""
    from datetime import date, timezone, timedelta

    if tool_name == "calculate_kbzhu":
        ingredients = args.get("ingredients", [])
        total = {"kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "grams": 0}
        breakdown = []
        for ing in ingredients:
            g = ing.get("grams", 0)
            mult = g / 100
            k = round(ing.get("kcal_per_100g", 0) * mult, 1)
            p = round(ing.get("protein_per_100g", 0) * mult, 1)
            f = round(ing.get("fat_per_100g", 0) * mult, 1)
            c = round(ing.get("carbs_per_100g", 0) * mult, 1)
            total["kcal"] += k; total["protein"] += p
            total["fat"] += f; total["carbs"] += c; total["grams"] += g
            breakdown.append(f"{ing['name']} {g}г → {k} ккал")
        return {
            "success": True,
            "dish": args.get("dish_name"),
            "total_kcal": round(total["kcal"]),
            "protein": round(total["protein"], 1),
            "fat": round(total["fat"], 1),
            "carbs": round(total["carbs"], 1),
            "total_grams": round(total["grams"]),
            "breakdown": breakdown,
            "ui_action": "show_kbzhu",
        }

    elif tool_name == "add_food_to_diary":
        from datetime import timezone, timedelta, date as date_cls
        utc_now = datetime.now(timezone.utc)
        minsk = utc_now + timedelta(hours=3)
        day = minsk.day
        item = {
            "n": f"{args['name']} {args.get('grams',100)}г",
            "k": args.get("kcal", 0),
            "b": args.get("protein", 0),
            "j": args.get("fat", 0),
            "u": args.get("carbs", 0)
        }
        if user_id:
            today_key = f"day_{day}_" + date_cls.today().strftime("%a %b %d %Y") + "_foods"
            from database import get_user_data, save_user_data
            foods = await get_user_data(user_id, today_key) or []
            foods.append(item)
            await save_user_data(user_id, today_key, foods)
        return {
            "success": True,
            "ui_action": "add_to_diary",
            "item": {**args, **item},
            "message": f"✅ Добавлено в дневник: {args['name']} {args.get('grams',100)}г — {args.get('kcal',0)} ккал"
        }

    elif tool_name == "update_product_price":
        if user_id:
            from database import get_user_data, save_user_data
            prices = await get_user_data(user_id, "custom_prices") or {}
            key = args["product_name"].lower()
            prices[key] = {
                "name": args["product_name"],
                "price": args["price_byn"],
                "unit": args.get("unit", "кг"),
                "store": args.get("store", "не указан"),
                "updated": datetime.now().strftime("%d.%m %H:%M")
            }
            await save_user_data(user_id, "custom_prices", prices)
        return {
            "success": True,
            "ui_action": "price_updated",
            "product": args["product_name"],
            "price": args["price_byn"],
            "unit": args.get("unit"),
            "store": args.get("store", ""),
            "message": f"Цена обновлена: {args['product_name']} — {args['price_byn']} BYN/{args.get('unit','кг')}"
        }

    elif tool_name == "add_to_shopping_list":
        item = {
            "name": args["product_name"],
            "qty": args.get("quantity", "1 шт"),
            "price": args.get("price_byn", 0),
            "category": args.get("category", "Прочее"),
            "added": datetime.now().strftime("%d.%m"),
            "checked": False
        }
        if user_id:
            from database import get_user_data, save_user_data
            shop = await get_user_data(user_id, "ai_shopping_list") or []
            shop.append(item)
            await save_user_data(user_id, "ai_shopping_list", shop)
        return {
            "success": True,
            "ui_action": "add_to_shop",
            "item": item,
            "message": f"✅ Добавлено в список покупок: {args['product_name']} {args.get('quantity','')}"
        }

    elif tool_name == "add_to_menu":
        utc_now = datetime.now(timezone.utc)
        minsk = utc_now + timedelta(hours=3)
        day = args.get("day", minsk.day)
        if user_id:
            from database import get_user_data, save_user_data
            menu_key = f"menu_day_{day}"
            menu = await get_user_data(user_id, menu_key) or {
                "breakfast":[],"snack1":[],"lunch":[],"preworkout":[],
                "postworkout":[],"dinner":[],"sleep":[]
            }
            slot = args.get("meal_slot", "lunch")
            if slot not in menu:
                menu[slot] = []
            menu[slot].append({
                "n": args["dish_name"],
                "k": args["kcal"], "b": args["protein"],
                "j": args["fat"], "u": args["carbs"]
            })
            await save_user_data(user_id, menu_key, menu)
        return {
            "success": True,
            "ui_action": "add_to_menu",
            "day": day,
            "slot": args.get("meal_slot"),
            "dish": args["dish_name"],
            "message": f"Добавлено в меню {day} мая: {args['dish_name']} — {args['kcal']} ккал"
        }

    elif tool_name == "search_product_kbzhu":
        grams = args.get("grams", 100)
        mult = grams / 100
        kcal = round(args.get("kcal_per_100g", 0) * mult)
        protein = round(args.get("protein_per_100g", 0) * mult, 1)
        fat = round(args.get("fat_per_100g", 0) * mult, 1)
        carbs = round(args.get("carbs_per_100g", 0) * mult, 1)
        name = args["product_name"]

        result = {
            "success": True,
            "ui_action": "show_kbzhu",
            "dish": f"{name} {grams}г",
            "total_kcal": kcal,
            "protein": protein,
            "fat": fat,
            "carbs": carbs,
            "total_grams": grams,
            "breakdown": [
                f"{name} {grams}г → {kcal} ккал",
                f"Б:{protein}г / Ж:{fat}г / У:{carbs}г",
                f"(на 100г: {args.get('kcal_per_100g',0)} ккал)"
            ],
            "message": f"КБЖУ для {name} {grams}г: {kcal} ккал"
        }

        # Auto-add to diary if requested
        if args.get("add_to_diary") and user_id:
            from datetime import timezone, timedelta, date as date_cls
            utc_now = datetime.now(timezone.utc)
            minsk = utc_now + timedelta(hours=3)
            day = minsk.day
            today_key = f"day_{day}_" + date_cls.today().strftime("%a %b %d %Y") + "_foods"
            from database import get_user_data, save_user_data
            foods = await get_user_data(user_id, today_key) or []
            foods.append({"n": f"{name} {grams}г", "k": kcal, "b": protein, "j": fat, "u": carbs})
            await save_user_data(user_id, today_key, foods)
            result["ui_action"] = "show_kbzhu_and_add"

        return result

    return {"success": False, "message": "Неизвестный инструмент"}


async def build_system_prompt(user_id: int = None) -> str:
    """Build personalized system prompt with user's actual data"""
    from datetime import timezone, timedelta
    utc_now = datetime.now(timezone.utc)
    minsk = utc_now + timedelta(hours=3)
    day = minsk.day
    month = minsk.month

    base = BASE_SYSTEM_PROMPT

    # Today's schedule context
    is_day_shift = day in DAY_SHIFTS
    is_night_shift = day in NIGHT_SHIFTS
    is_rest = not is_day_shift and not is_night_shift
    shift_str = "дневная смена (9:00-21:00)" if is_day_shift else "ночная смена (21:00-9:00)" if is_night_shift else "выходной день"
    workout_today = TRAIN_DAYS.get(day)

    today_context = f"""

КОНТЕКСТ СЕГОДНЯ ({day} мая, {minsk.strftime('%H:%M')} Минск):
- Смена: {shift_str}
- Тренировка сегодня: {workout_today if workout_today else 'нет, день отдыха'}
- {'После ночной смены нужно поспать приоритет 1' if is_night_shift else ''}"""

    if not user_id:
        return base + today_context

    try:
        ctx = await get_user_context(user_id)
        all_data = await get_user_data(user_id, "all") or {}

        # Today's tracker data
        from datetime import date
        today_key = f"day_{day}_" + date.today().strftime("%a %b %d %Y")
        water = all_data.get(today_key + "_water", 0)
        kcal = all_data.get(today_key + "_kcal", 0)
        foods_raw = all_data.get(today_key + "_foods", [])
        foods_str = ", ".join([f["n"] for f in foods_raw[-5:]]) if foods_raw else "ничего не записано"

        # Sleep today
        sleep_key = f"sleep_day_{day}"
        sleep_data = all_data.get(sleep_key, {})
        sleep_hours = sleep_data.get("hours", 0) if sleep_data else 0

        user_context = f"""

ДАННЫЕ МАКСИМА ИЗ ПРИЛОЖЕНИЯ:
Замеры (последние):
- Дата: {ctx['last_measure_date']}
- Вес: {ctx['weight']} кг
- Грудь: {ctx['chest']} см | Талия: {ctx['waist']} см | Бицепс: {ctx['bicep']} см
- Тренировок в мае: {ctx['done_trainings']} из 18

Сегодня ({day} мая):
- Сон: {sleep_hours if sleep_hours else 'не записан'} {'ч' if sleep_hours else ''}
- Вода: {water} мл из 2500 мл цели
- Калории: {kcal} из 2800 ккал цели
- Съел сегодня: {foods_str}

Учитывай эти данные в каждом ответе про питание, восстановление и тренировки."""

        return base + today_context + user_context
    except Exception as e:
        logger.error(f"build_system_prompt error: {e}")
        return base + today_context

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

    # 1. Load history BEFORE saving new message
    if uid:
        db_history = await get_chat_history(uid)
        system_prompt = await build_system_prompt(uid)
    else:
        db_history = body.get("history", [])
        system_prompt = await build_system_prompt()

    # 2. Build messages
    messages = [{"role": "system", "content": system_prompt}]
    for h in db_history[-12:]:
        role = "user" if h.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": h.get("text", "")})
    messages.append({"role": "user", "content": message})

    # 3. First call WITH tools
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "tools": AI_TOOLS,
        "tool_choice": "auto",
        "temperature": 0.6,
        "max_tokens": 800,
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

    response_msg = data["choices"][0]["message"]
    tool_calls = response_msg.get("tool_calls") or []
    tool_results = []

    # 4. Execute tool calls if any
    if tool_calls:
        import json as json_module
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json_module.loads(tc["function"]["arguments"])
            except Exception:
                fn_args = {}
            logger.info(f"Tool call: {fn_name}({fn_args})")
            result = await execute_tool(fn_name, fn_args, uid)
            tool_results.append(result)

        # 5. Second call with tool results for final reply
        messages.append({"role": "assistant", "tool_calls": tool_calls, "content": response_msg.get("content") or ""})
        for i, tc in enumerate(tool_calls):
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": str(tool_results[i].get("message", "OK"))
            })

        payload2 = {
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 600,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp2 = await client.post(
                GROQ_URL, json=payload2,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            )
            data2 = resp2.json()

        if resp2.status_code == 200:
            reply = data2["choices"][0]["message"].get("content", "Готово!")
        else:
            reply = response_msg.get("content") or "Готово!"
    else:
        reply = response_msg.get("content", "")

    # 6. Save to history
    if uid:
        await save_chat_message(uid, "user", message)
        await save_chat_message(uid, "assistant", reply)

    return {
        "reply": reply,
        "tool_results": tool_results,
        "tools_used": [tc["function"]["name"] for tc in tool_calls]
    }


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


# Simple KBZHU database (common products per 100g)
KBZHU_DB = {
    "курица": {"k":165,"b":31,"j":3.6,"u":0},
    "куриная грудка": {"k":165,"b":31,"j":3.6,"u":0},
    "куриное филе": {"k":165,"b":31,"j":3.6,"u":0},
    "говядина": {"k":254,"b":26,"j":16,"u":0},
    "свинина": {"k":297,"b":25,"j":21,"u":0},
    "рыба": {"k":95,"b":18,"j":2,"u":0},
    "хек": {"k":95,"b":18,"j":2,"u":0},
    "минтай": {"k":92,"b":18,"j":1,"u":0},
    "лосось": {"k":208,"b":25,"j":12,"u":0},
    "тунец": {"k":96,"b":22,"j":1,"u":0},
    "яйцо": {"k":157,"b":12.7,"j":11.5,"u":0.7},
    "яйца": {"k":157,"b":12.7,"j":11.5,"u":0.7},
    "творог": {"k":121,"b":17,"j":5,"u":2},
    "молоко": {"k":52,"b":2.9,"j":2.5,"u":4.7},
    "кефир": {"k":40,"b":3.2,"j":1,"u":4},
    "сыр": {"k":350,"b":25,"j":27,"u":0},
    "гречка": {"k":110,"b":4,"j":1,"u":21},
    "рис": {"k":130,"b":2.7,"j":0.3,"u":28},
    "овсянка": {"k":88,"b":3,"j":1.5,"u":15},
    "паста": {"k":158,"b":5.5,"j":0.9,"u":31},
    "картофель": {"k":82,"b":2,"j":0.1,"u":18},
    "банан": {"k":89,"b":1.1,"j":0.3,"u":23},
    "яблоко": {"k":52,"b":0.3,"j":0.2,"u":14},
    "мёд": {"k":304,"b":0.3,"j":0,"u":82},
    "орехи": {"k":650,"b":16,"j":62,"u":13},
    "грецкие орехи": {"k":654,"b":15,"j":65,"u":7},
    "арахисовая паста": {"k":588,"b":25,"j":50,"u":20},
    "масло": {"k":884,"b":0,"j":100,"u":0},
    "хлеб": {"k":247,"b":9,"j":3.5,"u":43},
    "гейнер": {"k":380,"b":25,"j":4,"u":62},
    "омлет": {"k":184,"b":13,"j":14,"u":2},
    "перец": {"k":26,"b":1,"j":0.2,"u":6},
    "помидор": {"k":18,"b":0.9,"j":0.2,"u":3.7},
    "огурец": {"k":15,"b":0.7,"j":0.1,"u":3},
    "морковь": {"k":35,"b":0.9,"j":0.2,"u":8},
    "лук": {"k":40,"b":1.1,"j":0.1,"u":9},
}

@app.post("/api/kbzhu")
async def get_kbzhu(request: Request):
    """Fast KBZHU lookup — DB first, then AI"""
    body = await request.json()
    product = body.get("product", "").strip().lower()
    grams = float(body.get("grams", 100))

    # Search in local DB
    found = None
    for key, val in KBZHU_DB.items():
        if key in product or product in key:
            found = val
            break

    if found:
        mult = grams / 100
        return {
            "kcal": round(found["k"] * mult),
            "protein": round(found["b"] * mult, 1),
            "fat": round(found["j"] * mult, 1),
            "carbs": round(found["u"] * mult, 1),
            "source": "db"
        }

    # Ask Groq with strict JSON response
    if not GROQ_API_KEY:
        return {"error": "not found"}

    prompt = f"""Дай КБЖУ для "{product}" на 100г. Отвечай ТОЛЬКО JSON без текста:
{{"kcal": число, "protein": число, "fat": число, "carbs": число}}
Только цифры, без единиц измерения. Если не знаешь — используй ближайший аналог."""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                GROQ_URL,
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 60,
                },
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            )
            data = resp.json()

        if resp.status_code == 200:
            import json as json_mod, re
            text = data["choices"][0]["message"]["content"].strip()
            # Extract JSON from response
            match = re.search(r'\{[^}]+\}', text)
            if match:
                vals = json_mod.loads(match.group())
                mult = grams / 100
                return {
                    "kcal": round(float(vals.get("kcal", 0)) * mult),
                    "protein": round(float(vals.get("protein", 0)) * mult, 1),
                    "fat": round(float(vals.get("fat", 0)) * mult, 1),
                    "carbs": round(float(vals.get("carbs", 0)) * mult, 1),
                    "source": "ai"
                }
    except Exception as e:
        logger.error(f"KBZHU AI error: {e}")

    return {"error": "not found"}


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
