"""HTTP-обвязка бота.

Веб-сервер здесь нужен ради одного маршрута — точки входа Telegram. Именно
входящий запрос будит спящий контейнер на бесплатном тарифе, поэтому бот
отвечает с задержкой на холодный старт, а не пропадает.
"""

import base64
import binascii
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from bot import telegram_bot
from config import config
from utils import lavatop, site
from utils.content_library import library, tags_for_text


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


def _secret_matches(provided: str, expected: str) -> bool:
    """Совпал ли присланный секрет с нашим.

    Сравниваем байты, а не строки: `compare_digest` на строках с не-ASCII
    бросает TypeError, и один заголовок с кириллицей превращал отказ в
    пятисотку — посреди приёма платежа, где ошибка сервера означает, что
    касса будет ретраить, а мы каждый раз падать.

    Постоянное время сравнения нужно по-прежнему: обычное `==` заканчивается
    на первом несовпавшем байте, и по времени ответа секрет подбирается.
    """
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


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
    if not _secret_matches(provided, config.TASKS_SECRET):
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


@app.get("/tasks/library")
async def inspect_library(request: Request):
    """Почему к ответу не прикрепился ролик.

    Вопрос задавался уже дважды, и оба раза ответ был в двух числах, которых
    неоткуда взять: сколько роликов по этой теме вообще есть и сколько из них
    человеку видно. В логе остаётся только «ролик не подобран» — верно, но
    неотличимо от «библиотека пуста» и от «всё уже показано».

    `?q=` — прогнать запрос через тот же подбор, что в диалоге.
    `?chat=` — от лица конкретного человека: с его подпиской и его просмотрами.

    Только чтение, под тем же секретом, что остальные служебные маршруты:
    здесь видно, кто что смотрел.
    """
    if not config.TASKS_SECRET:
        raise HTTPException(status_code=503, detail="TASKS_SECRET not set")
    provided = request.headers.get("X-Tasks-Secret") or request.query_params.get("key", "")
    if not _secret_matches(provided, config.TASKS_SECRET):
        raise HTTPException(status_code=403, detail="bad secret")

    chat_id = request.query_params.get("chat", "")
    query = request.query_params.get("q", "")

    is_premium, seen = False, ()
    if chat_id:
        state = store.user(chat_id)
        is_premium, seen = state.is_premium, state.seen_content

    items = [
        {
            "message_id": item.message_id,
            "tier": item.tier,
            "topics": sorted(library.topics_of(item)),
            "title": item.title,
            "seen": item.message_id in seen,
        }
        for item in library.all()
    ]

    answer: dict[str, Any] = {
        "ok": True,
        "total": len(items),
        "premium_only": sum(1 for i in items if i["tier"] == "premium"),
        "items": items,
    }
    if chat_id:
        answer["viewer"] = {
            "chat": chat_id,
            "is_premium": is_premium,
            "seen": len(seen),
            "visible": sum(
                1 for i in items
                if not i["seen"] and (is_premium or i["tier"] != "premium")
            ),
        }
    if query:
        wanted = sorted(tags_for_text(query))
        picked = library.match(query, is_premium=is_premium, exclude=seen)
        answer["query"] = {
            "text": query,
            "tags": wanted,
            "picked": picked.message_id if picked else None,
            # Почему не подобралось: те же ролики, но без фильтров.
            "on_topic": [
                {"message_id": i["message_id"], "tier": i["tier"], "seen": i["seen"]}
                for i in items
                if set(wanted) & set(i["topics"])
            ],
        }
    return answer


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
    if not _secret_matches(provided, config.TASKS_SECRET):
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


@app.api_route("/tasks/lavatop", methods=["GET", "POST"])
async def lavatop_cabinet(request: Request):
    """Прочитать кабинет LavaTop или переписать оффер.

    Ключ живёт в переменных сервиса, поэтому к кассе ходит сервис, а не
    чья-то машина: секрет не покидает Render.

    `action=list` — только чтение: что уже заведено, с идентификаторами
    продуктов и офферов. С них начинается любая правка, потому что создавать
    продукты их API не умеет — карточки заводятся руками в кабинете.

    `action=update` — переписать один оффер: `product`, `offer`, и любое из
    `name`, `description`, `price_rub`, `price_usd`, `price_eur`.
    """
    if not config.TASKS_SECRET:
        raise HTTPException(status_code=503, detail="TASKS_SECRET not set")
    provided = request.headers.get("X-Tasks-Secret") or request.query_params.get("key", "")
    if not _secret_matches(provided, config.TASKS_SECRET):
        raise HTTPException(status_code=403, detail="bad secret")
    if not config.LAVA_API_KEY:
        raise HTTPException(status_code=503, detail="LAVA_API not set")

    action = request.query_params.get("action", "list")
    try:
        if action == "list":
            products = await lavatop.list_products(config.LAVA_API_KEY)
            return {"ok": True, "count": len(products), "products": [p.brief() for p in products]}

        if action == "update":
            product_id = request.query_params.get("product", "")
            offer_id = request.query_params.get("offer", "")
            if not product_id or not offer_id:
                raise HTTPException(status_code=400, detail="product and offer are required")

            prices = {
                currency: float(request.query_params[key])
                for currency, key in (("RUB", "price_rub"), ("USD", "price_usd"), ("EUR", "price_eur"))
                if request.query_params.get(key)
            }
            result = await lavatop.update_offer(
                config.LAVA_API_KEY,
                product_id,
                offer_id,
                name=request.query_params.get("name"),
                description=request.query_params.get("description"),
                prices=prices or None,
            )
            return {"ok": True, "product": result.get("title"), "offers": result.get("offers")}
    except lavatop.LavaError as e:
        # Ошибку кассы отдаём как есть: угадывать её причину дороже, чем
        # прочитать.
        log_agent_action("Lava", f"Касса отказала: {e}", level="ERROR")
        raise HTTPException(status_code=502, detail=str(e))

    raise HTTPException(status_code=400, detail="action must be list or update")


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

    if not _webhook_is_ours(request):
        log_agent_action("Payments", "Уведомление LavaTop с неверным ключом", level="WARNING")
        raise HTTPException(status_code=403, detail="bad secret")

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be json")

    # Целиком и до разбора: дешевле один раз посмотреть, чем гадать.
    log_agent_action("Payments", f"LavaTop прислал: {payload}")

    # Уведомление приходит и на неудачную оплату — тем же адресом, с тем же
    # покупателем, отличаясь только статусом. Раньше здесь статус не
    # проверялся вовсе: `payment.failed` открывал доступ ровно так же, как
    # успешная оплата.
    if not _is_paid(payload):
        log_agent_action(
            "Payments",
            f"Уведомление не об оплате — доступ не выдаём: "
            f"{payload.get('eventType')} / {payload.get('status')}",
        )
        return {"ok": True, "granted": False, "reason": "not a completed payment"}

    chat_id = _buyer_chat_id(payload)
    if not chat_id:
        # Заплатили на витрине, а не по счёту из бота: метки там взяться
        # неоткуда. Остаётся почта — единственное, что знают обе стороны.
        chat_id = _chat_by_email(payload)

    if not chat_id:
        log_agent_action(
            "Payments",
            "Не понять, кому выдать доступ: ни метки чата, ни знакомой почты. "
            f"Почта покупателя: {_buyer_email(payload) or '—'}. Человек напишет "
            "её боту сам — тогда доступ откроется по сверке с кассой.",
            level="ERROR",
        )
        # 200, а не ошибка: LavaTop иначе будет ретраить бесконечно, а платёж
        # состоялся. Разбираемся по логу и выдаём доступ руками.
        return {"ok": True, "granted": False, "reason": "no buyer id"}

    await telegram_bot.grant_premium(chat_id, "lavatop", payload=str(payload)[:500])
    return {"ok": True, "granted": True}


def _webhook_is_ours(request: Request) -> bool:
    """Уведомление действительно от кассы?

    Касса подписывает вебхуки одним из двух способов — так сказано в её
    спецификации, и какой из них окажется в кабинете, заранее не известно:

    * `X-Api-Key: <секрет>` — ровно наш секрет заголовком;
    * HTTP Basic — логин и пароль, склеенные через двоеточие.

    Поддерживаем оба, иначе настройка упрётся в то, какой вариант касса
    предложит в форме. Для Basic принимаем и «логин:пароль» целиком, и один
    пароль: в форме бывает и то и другое поле, а угадывать, что человек
    записал в переменную, дороже, чем принять оба.

    Само сравнение — в `_secret_matches`.
    """
    secret = config.LAVATOP_SECRET or ""

    candidates = [
        request.headers.get("X-Api-Key") or "",
        request.headers.get("X-Signature") or "",
        request.query_params.get("key", ""),
    ]

    authorization = request.headers.get("Authorization") or ""
    if authorization.lower().startswith("basic "):
        try:
            pair = base64.b64decode(authorization[6:].strip()).decode("utf-8", "replace")
        except (ValueError, binascii.Error):
            pair = ""
        if pair:
            candidates.append(pair)
            candidates.append(pair.partition(":")[2])

    return any(_secret_matches(value, secret) for value in candidates)


#: Событие и статус успешной оплаты. Подписка присылает своё событие на
#: каждое списание — доступ надо продлевать по каждому.
_PAID_EVENTS = {
    "payment.success",
    "subscription.recurring.payment.success",
}


def _is_paid(payload: dict) -> bool:
    """Это уведомление об успешно прошедшей оплате?

    Проверяем и событие, и статус: событие говорит, что произошло, статус —
    чем кончилось, и совпасть они обязаны оба.
    """
    if not isinstance(payload, dict):
        return False
    event = str(payload.get("eventType") or "").strip().lower()
    status = str(payload.get("status") or "").strip().lower()
    if event and event not in _PAID_EVENTS:
        return False
    if status and status not in ("completed", "active", "subscription-active"):
        return False
    # Пустые оба — формат не тот, что в спецификации. Молча выдавать доступ
    # по неизвестному уведомлению нельзя.
    return bool(event or status)


def _buyer_email(payload: dict) -> str:
    buyer = payload.get("buyer") if isinstance(payload, dict) else None
    if isinstance(buyer, dict):
        return str(buyer.get("email") or "").strip().lower()
    return ""


def _chat_by_email(payload: dict) -> str:
    """Чат по почте покупателя — если он называл её боту раньше."""
    email = _buyer_email(payload)
    if not email:
        return ""
    for state in store.all_users():
        if state.email and state.email.strip().lower() == email:
            return state.chat_id
    return ""


def _buyer_chat_id(payload: dict) -> str:
    """Найти идентификатор покупателя в теле уведомления.

    Первым делом — метка, которую бот сам положил в счёт: касса возвращает
    `clientUtm` как есть, и это самый надёжный путь. Остальные места
    остались с тех пор, когда формат уведомления не был сверен.
    """
    if not isinstance(payload, dict):
        return ""
    utm = payload.get("clientUtm")
    candidates = [
        utm.get("utm_content") if isinstance(utm, dict) else None,
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
