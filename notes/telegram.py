"""Тонкий клиент Bot API поверх aiohttp.

Почему не python-telegram-bot, который уже есть в зависимостях: он поднимает
своё приложение с очередью и жизненным циклом, и второе такое в одном процессе
означало бы вторую фоновую машинерию рядом с ботом Федерации. Здесь нужно три
метода, и три метода дешевле подружить, чем два фреймворка.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from . import config

API = "https://api.telegram.org"

#: Больше половины минуты ждать нечего: Telegram отвечает быстро, а зависший
#: запрос держал бы соединение и фоновую задачу.
TIMEOUT = aiohttp.ClientTimeout(total=45)


async def _call(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{API}/bot{config.BOT_TOKEN}/{method}"
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(url, json=payload) as response:
            data = await response.json()
    if not data.get("ok"):
        raise RuntimeError(f"{method}: {data.get('description', 'unknown error')}")
    return data.get("result", {})


async def send_message(chat_id: int | str, text: str, reply_to: int | None = None) -> None:
    """Отправить текст.

    Без разметки намеренно. В расшифровке встречается что угодно — звёздочки,
    подчёркивания, угловые скобки, — и разбор разметки на таком тексте
    заканчивается ошибкой Telegram вместо доставленной заметки.
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
        # Ответ на сообщение, которое успели удалить, иначе роняет отправку.
        payload["allow_sending_without_reply"] = True
    await _call("sendMessage", payload)


async def download_file(file_id: str) -> bytes:
    """Скачать вложение по его идентификатору.

    Два запроса: сначала getFile отдаёт путь, потом путь качается отдельным
    адресом. Так устроен Bot API, обойти нечем.
    """
    meta = await _call("getFile", {"file_id": file_id})
    path = meta.get("file_path")
    if not path:
        raise RuntimeError("getFile не вернул file_path")

    url = f"{API}/file/bot{config.BOT_TOKEN}/{path}"
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()
