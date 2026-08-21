"""HTTP-обвязка бота.

Веб-сервер здесь нужен ради одного маршрута — точки входа Telegram. Именно
входящий запрос будит спящий контейнер на бесплатном тарифе, поэтому бот
отвечает с задержкой на холодный старт, а не пропадает.
"""

import os
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from bot import telegram_bot
from config import config
from utils.funnel_store import store
from utils.logger import get_recent_logs, log_agent_action


@asynccontextmanager
async def lifespan(app: FastAPI):
    await telegram_bot.start()
    yield
    await telegram_bot.stop()


app = FastAPI(title="Health Funnel Bot", lifespan=lifespan)

log_agent_action("App", "🚀 Бот запускается")


@app.get("/")
async def root():
    return {"status": "ok", "service": "health-funnel-bot"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/debug")
async def debug_info():
    """Последние строки лога — чтобы смотреть состояние без доступа к хостингу."""
    return {
        "mode": "webhook" if telegram_bot.webhook_url else "polling",
        "channel_configured": bool(config.CONTENT_CHANNEL_ID),
        "payments_enabled": config.PAYMENTS_ENABLED,
        # Какое хранилище реально поднялось. Проверять по переменной окружения
        # бесполезно: она задана, а база могла и не ответить.
        "store": getattr(store, "backend_name", "unknown"),
        "followups_scheduled": bool(config.TASKS_SECRET),
        "logs": get_recent_logs(),
    }


@app.api_route("/tasks/followups", methods=["GET", "POST"])
async def run_followups(request: Request):
    """Разослать созревшие догоняющие сообщения.

    Дёргается внешним расписанием (Render Cron Job). Планировщик внутри
    процесса здесь не работает: на бесплатном тарифе контейнер засыпает через
    15 минут тишины, и его собственный таймер не проснётся — а внешний запрос
    контейнер будит.
    """
    if not config.TASKS_SECRET:
        raise HTTPException(status_code=503, detail="TASKS_SECRET not set")

    provided = request.headers.get("X-Tasks-Secret") or request.query_params.get("key", "")
    if not secrets.compare_digest(provided, config.TASKS_SECRET):
        log_agent_action("App", "Запуск рассылки с неверным ключом отклонён", level="WARNING")
        raise HTTPException(status_code=403, detail="bad secret")

    return {"ok": True, **await telegram_bot.run_followups()}


@app.post(telegram_bot.WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Точка входа Telegram.

    Отвечаем 200 сразу, обработку уводим в фон: Telegram ждёт ответа считанные
    секунды и при таймауте присылает апдейт заново — человек получил бы дубли.
    """
    accepted = await telegram_bot.handle_webhook(
        await request.json(),
        request.headers.get("X-Telegram-Bot-Api-Secret-Token"),
    )
    if not accepted:
        raise HTTPException(status_code=403, detail="bad secret")
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    log_agent_action("App", f"📡 Слушаю порт {port}")
    # Объект приложения, а не строка импорта: строка заставляет uvicorn
    # переимпортировать модуль и держать в памяти второй набор объектов.
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=config.LOG_LEVEL.lower())
