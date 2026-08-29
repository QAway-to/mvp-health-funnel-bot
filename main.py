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
from utils import site
from utils.content_library import library


def library_size() -> int:
    return len(library)
from utils.funnel_store import store
from utils.logger import get_recent_logs, log_agent_action


@asynccontextmanager
async def lifespan(app: FastAPI):
    await telegram_bot.start()
    yield
    await telegram_bot.stop()


app = FastAPI(title="Health Funnel Bot", lifespan=lifespan)

log_agent_action("App", "🚀 Бот запускается")
site.log_state()


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
        # Собрана ли статика лендингов. Отдельной строкой, потому что бот
        # поднимается и без неё, и молча отдавать 404 на весь сайт нельзя.
        "site_built": site.is_available(),
        # Состояние библиотеки роликов. Раньше ответ на «почему бот не
        # присылает видео» приходилось искать в логе, а он короткий и старые
        # строки из него вымываются. Теперь видно сразу: сколько роликов, по
        # каким темам и сколько не подберутся ни по одному запросу.
        "content": {
            "total": len(library),
            "premium_only": library.premium_count(),
            "untagged": len(library.untagged()),
            "topics": sorted(
                {topic for item in library._items.values() for topic in library.topics_of(item)}
            ),
        },
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


@app.api_route("/tasks/reindex", methods=["GET", "POST"])
async def run_reindex(request: Request):
    """Пересобрать индекс роликов по диапазону постов канала.

    Зачем маршрут, если есть команда /reindex: своих постов бот в
    `channel_post` не получает вовсе. Ролики, загруженные его же токеном,
    сами в библиотеку не попадут никогда, и переиндексация после заливки —
    не запасной путь, а единственный.

    Защита та же, что у рассылки: без TASKS_SECRET маршрут выключен.
    """
    if not config.TASKS_SECRET:
        raise HTTPException(status_code=503, detail="TASKS_SECRET not set")

    provided = request.headers.get("X-Tasks-Secret") or request.query_params.get("key", "")
    if not secrets.compare_digest(provided, config.TASKS_SECRET):
        log_agent_action("App", "Переиндексация с неверным ключом отклонена", level="WARNING")
        raise HTTPException(status_code=403, detail="bad secret")

    if not config.ADMIN_CHAT_ID:
        # Пересылать посты некуда: без этого подпись не прочитать.
        raise HTTPException(status_code=503, detail="ADMIN_CHAT_ID not set")

    try:
        start_id = int(request.query_params.get("from", "1"))
        end_id = int(request.query_params.get("to", "0"))
    except ValueError:
        raise HTTPException(status_code=400, detail="from/to must be integers")
    if end_id < start_id:
        raise HTTPException(status_code=400, detail="to must not be less than from")

    count = await telegram_bot.reindex_range(str(config.ADMIN_CHAT_ID), start_id, end_id)
    return {"ok": True, "indexed": count, "library": library_size()}


@app.post("/payments/lavatop")
async def lavatop_payment(request: Request):
    """Оплата картой на стороне LavaTop — выдать доступ в боте.

    Вторая дверь к тому же продукту: Telegram Stars работают только внутри
    Telegram, LavaTop принимает карту. Доступ обе выдают один и тот же, и
    выдаётся он тем же кодом, что после Stars.

    ФОРМАТ УВЕДОМЛЕНИЯ НЕ СВЕРЕН С ДОКУМЕНТАЦИЕЙ LAVATOP. Поэтому здесь два
    решения вместо одного:

    1. Тело запроса целиком пишется в лог. По первому же реальному платежу
       поля сверяются за пять минут — гадать по документации, которую я не
       читал, дороже.
    2. Идентификатор покупателя ищется в нескольких местах сразу. Какое из них
       окажется настоящим, покажет тот же первый платёж.

    Пока `LAVATOP_SECRET` не задан, маршрут выключен: открытая точка выдачи
    доступа означала бы, что премиум выпишет себе любой, кто знает адрес.
    """
    if not config.LAVATOP_SECRET:
        raise HTTPException(status_code=503, detail="LAVATOP_SECRET not set")

    provided = (
        request.headers.get("X-Api-Key")
        or request.headers.get("X-Signature")
        or request.query_params.get("key", "")
    )
    if not secrets.compare_digest(provided, config.LAVATOP_SECRET):
        log_agent_action("Payments", "Уведомление LavaTop с неверным ключом", level="WARNING")
        raise HTTPException(status_code=403, detail="bad secret")

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be json")

    # Целиком и до разбора: это единственный способ узнать настоящий формат.
    log_agent_action("Payments", f"LavaTop прислал: {payload}")

    chat_id = _buyer_chat_id(payload)
    if not chat_id:
        log_agent_action(
            "Payments",
            "В уведомлении нет chat_id покупателя — доступ выдать некому. "
            "Ссылка оплаты должна нести идентификатор, см. lavatop-products.md",
            level="ERROR",
        )
        # 200, а не ошибка: LavaTop иначе будет ретраить бесконечно, а платёж
        # состоялся. Разбираемся по логу и выдаём доступ руками.
        return {"ok": True, "granted": False, "reason": "no buyer id"}

    await telegram_bot.grant_premium(chat_id, "lavatop", payload=str(payload)[:500])
    return {"ok": True, "granted": True}


def _buyer_chat_id(payload: dict) -> str:
    """Найти идентификатор покупателя в теле уведомления.

    Мест несколько, потому что формат не сверен. Порядок — от самого явного к
    наименее: сначала то, что мы сами положили в ссылку оплаты.
    """
    if not isinstance(payload, dict):
        return ""
    candidates = [
        payload.get("client_id"),
        payload.get("clientId"),
        payload.get("custom"),
        payload.get("buyer_id"),
        (payload.get("buyer") or {}).get("id") if isinstance(payload.get("buyer"), dict) else None,
        (payload.get("data") or {}).get("client_id") if isinstance(payload.get("data"), dict) else None,
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text.isdigit():
            return text
    return ""


@app.get("/{url_path:path}")
async def landing(url_path: str, request: Request):
    """Лендинги — тем же процессом, что принимает вебхук.

    Маршрут объявлен последним намеренно: FastAPI разбирает их по порядку
    регистрации, поэтому `/health`, `/debug`, `/tasks/*` и вебхук перехватят
    свои адреса раньше, а сюда попадёт только то, что действительно сайт.

    Здесь же остаётся корень: раньше он отдавал `{"status": "ok"}`, теперь —
    главную. Проверять живость нужно по `/health`, он для этого и заведён.
    """
    return site.response_for(
        "/" + url_path.lstrip("/"),
        request.headers.get("Accept-Encoding", ""),
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    log_agent_action("App", f"📡 Слушаю порт {port}")
    # Объект приложения, а не строка импорта: строка заставляет uvicorn
    # переимпортировать модуль и держать в памяти второй набор объектов.
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=config.LOG_LEVEL.lower())
