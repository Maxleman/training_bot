# 🏋 Training Bot — Инструкция по запуску

## Что внутри
- `main.py` — сервер (FastAPI)
- `database.py` — база данных (PostgreSQL)
- `static/index.html` — Mini App (весь фронтенд)
- `requirements.txt` — зависимости Python
- `railway.toml` — конфиг для Railway

---

## Шаг 1 — Загрузи на GitHub

1. Зайди на **github.com**
2. Нажми **"+" → New repository**
3. Назови: `training-bot`
4. Поставь **Public**
5. Нажми **Create repository**
6. На странице репозитория нажми **"Add file → Upload files"**
7. Перетащи ВСЕ файлы из этой папки (включая папку `static`!)
8. Нажми **Commit changes**

---

## Шаг 2 — Создай проект на Railway

1. Зайди на **railway.app**
2. Нажми **"New Project"**
3. Выбери **"Deploy from GitHub repo"**
4. Найди `training-bot` → выбери его
5. Railway начнёт деплой (подождёт ~2 минуты)

---

## Шаг 3 — Добавь базу данных

1. В проекте Railway нажми **"+ New"**
2. Выбери **"Database → Add PostgreSQL"**
3. База создастся автоматически
4. Railway сам добавит переменную `DATABASE_URL` в твой сервис

---

## Шаг 4 — Добавь переменные окружения

В Railway → твой сервис → вкладка **"Variables"** → добавь:

```
BOT_TOKEN    = твой_токен_от_BotFather
WEBHOOK_URL  = https://твой-проект.up.railway.app
```

`WEBHOOK_URL` — это URL который Railway показывает после деплоя
(вкладка Settings → Networking → Public URL)

---

## Шаг 5 — Получи URL и настрой бота

1. В Railway → Settings → Networking → **Generate Domain**
2. Скопируй URL (например `https://training-bot-production.up.railway.app`)
3. Вставь его в переменную `WEBHOOK_URL`
4. Сервис перезапустится автоматически

---

## Шаг 6 — Создай Mini App в BotFather

1. Напиши **@BotFather** в Telegram
2. `/newapp`
3. Выбери своего бота
4. Название: `Тренировки Май`
5. URL: `https://твой-проект.up.railway.app/app`
6. BotFather даст ссылку вида `t.me/твой_бот/app`

---

## Готово! 🎉

Открой ссылку `t.me/твой_бот/app` в Telegram.

### Команды бота:
- `/start` — главное меню с кнопкой открытия приложения
- `/today` — что сегодня за тренировка
- `/notify` — включить уведомления (приходят в 9:00 по Минску)
- `/stats` — быстрая статистика

### Уведомления
Каждый день тренировки в **9:00 по Минску** бот автоматически пришлёт:
- Название тренировки
- Напоминание про питание
- Кнопку открытия приложения

---

## Если что-то не работает

- Логи смотри в Railway → твой сервис → вкладка **"Logs"**
- Самая частая проблема: неправильный `WEBHOOK_URL` (должен быть без `/` в конце)
- Если бот не отвечает: проверь `BOT_TOKEN` — скопирован ли полностью?
