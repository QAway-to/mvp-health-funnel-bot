"""Конфигурация бота. Всё берётся из окружения, значений в коде нет."""

import os
from typing import Optional

from dotenv import load_dotenv

try:
    load_dotenv()
except Exception:
    pass


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_BOT_ENABLED: bool = _flag("TELEGRAM_BOT_ENABLED", "true")
    # Приватный канал-библиотека роликов, вид -100...
    CONTENT_CHANNEL_ID: Optional[str] = os.getenv("CONTENT_CHANNEL_ID")
    # Личный chat_id владельца: доступ к служебным командам и алерты о сбоях.
    ADMIN_CHAT_ID: Optional[str] = os.getenv("ADMIN_CHAT_ID")

    # --- Webhook ---
    # Публичный адрес сервиса; на Render подставляется сам. Если задан — бот
    # работает вебхуком: спящий контейнер будит входящий запрос Telegram,
    # поэтому сообщения не теряются. Пусто — поллинг (локальная разработка).
    PUBLIC_URL: Optional[str] = os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

    # --- Воронка ---
    FUNNEL_CTA_AT: int = int(os.getenv("FUNNEL_CTA_AT", "5"))
    # Ключ для служебного маршрута рассылки. Пока не задан, маршрут выключен:
    # открытая точка запуска позволила бы кому угодно слать письма нашей базе.
    TASKS_SECRET: Optional[str] = os.getenv("TASKS_SECRET")
    PURCHASE_URL: Optional[str] = os.getenv("PURCHASE_URL")
    # Общий секрет с LavaTop: им подписан вебхук об оплате картой. Пока пусто —
    # маршрут выключен целиком. Открытая точка выдачи доступа означала бы, что
    # премиум может выписать себе кто угодно, зная адрес.
    LAVATOP_SECRET: Optional[str] = os.getenv("LAVATOP_SECRET")

    # Идентификаторы цен в кассе — по одному на ступень. Не секрет: их видно
    # в любом ответе `GET /products`, и вынесены они сюда не ради тайны, а
    # чтобы смена тарифа не требовала выката кода.
    #
    # Без них бот не может выставить счёт и уводит человека на витрину, где
    # платёж уже не с кем связать.
    LAVATOP_OFFER_BASE: str = os.getenv(
        "LAVATOP_OFFER_BASE", "af5d5b68-89f2-4bb6-8880-8d89c8aa55f5"
    )
    LAVATOP_OFFER_PREMIUM: str = os.getenv(
        "LAVATOP_OFFER_PREMIUM", "0213ac07-56d5-42cc-b859-686caa641da6"
    )
    LAVATOP_OFFER_PRO: str = os.getenv(
        "LAVATOP_OFFER_PRO", "ede38814-fd69-4978-9345-13c643ccc61e"
    )
    #: Валюта счёта. Совпадает с ценой на кнопке — расходиться им нельзя.
    LAVATOP_CURRENCY: str = os.getenv("LAVATOP_CURRENCY", "USD")
    # Ключ к публичному API кассы: им читается список продуктов и правятся
    # офферы. Лежит в переменных сервиса и никуда оттуда не уезжает — к API
    # ходит сам сервис. Имя LAVA_API — то, под которым ключ уже заведён;
    # второе оставлено на случай переименования.
    LAVA_API_KEY: Optional[str] = os.getenv("LAVA_API") or os.getenv("LAVATOP_API_KEY")
    PAYMENTS_ENABLED: bool = _flag("PAYMENTS_ENABLED")
    # Цена ступени в звёздах Telegram. Ноль означает «в звёздах не продаём» —
    # такая ступень уходит на внешнюю страницу оплаты.
    #
    # Значения по умолчанию посчитаны от курса, который заказчик проверил в
    # Telegram 28.08.2026: 2500 звёзд ≈ $40, то есть примерно 62,5 звезды за
    # доллар. Отсюда $10 → 625, $20 → 1250, $100 → 6250.
    #
    # Курс плавает и в мелких пачках звёзды дороже, поэтому числа остаются
    # переопределяемыми из окружения: текст правит тот, кто пишет тексты,
    # деньги задаёт тот, у кого доступ к кассе. Но раньше значение по
    # умолчанию (1000 звёзд на все ступени) не соответствовало ни одной цене
    # на сайте — а это ровно тот случай, когда человек платит не ту сумму.
    STARS_PER_DOLLAR: float = float(os.getenv("STARS_PER_DOLLAR", "62.5"))
    STARS_PRICE: int = int(os.getenv("STARS_PRICE", "1250"))
    STARS_PRICE_BASE: int = int(os.getenv("STARS_PRICE_BASE", "0")) or 625
    STARS_PRICE_PREMIUM: int = int(os.getenv("STARS_PRICE_PREMIUM", "0")) or STARS_PRICE
    STARS_PRICE_PRO: int = int(os.getenv("STARS_PRICE_PRO", "0")) or 6250

    # --- LLM ---
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    # --- Google Sheets (состояние и аналитика; необязательно) ---
    SHEETS_SCRIPT_URL: Optional[str] = os.getenv("SHEETS_SCRIPT_URL")
    SHEETS_SECRET: Optional[str] = os.getenv("SHEETS_SECRET")


config = Config()
