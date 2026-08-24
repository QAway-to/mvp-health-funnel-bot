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
    PAYMENTS_ENABLED: bool = _flag("PAYMENTS_ENABLED")
    # Цена ступени в звёздах Telegram. Ноль означает «в звёздах не продаём» —
    # такая ступень уходит на внешнюю страницу оплаты. Курс звезды к доллару
    # тут не считается: он меняется, и придуманное число обмануло бы кассу.
    STARS_PRICE: int = int(os.getenv("STARS_PRICE", "1000"))
    STARS_PRICE_BASE: int = int(os.getenv("STARS_PRICE_BASE", "0"))
    STARS_PRICE_PREMIUM: int = int(os.getenv("STARS_PRICE_PREMIUM", "0")) or STARS_PRICE
    STARS_PRICE_PRO: int = int(os.getenv("STARS_PRICE_PRO", "0"))

    # --- LLM ---
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    # --- Google Sheets (состояние и аналитика; необязательно) ---
    SHEETS_SCRIPT_URL: Optional[str] = os.getenv("SHEETS_SCRIPT_URL")
    SHEETS_SECRET: Optional[str] = os.getenv("SHEETS_SECRET")


config = Config()
