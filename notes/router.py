"""Вебхук личного бота заметок.

Сценарий один и короткий: пришло сообщение — голосовое своё, пересланное чужое
или просто текст — бот делает из него заметку и отвечает расшифровкой. Если в
подписи попросили календарь и в тексте нашлась дата, добавляет ссылку на
создание события.

ЧУЖИЕ НЕ ОБСЛУЖИВАЮТСЯ И НЕ УВЕДОМЛЯЮТСЯ. Бота найдут поиском, и ответ «вам
сюда нельзя» подтвердил бы, что он живой и чей-то. Молчание не сообщает ничего.

ОТВЕЧАЕМ 200 СРАЗУ, РАБОТАЕМ В ФОНЕ. Telegram ждёт ответа считанные секунды и
при таймауте присылает апдейт заново — расшифровка на минуту означала бы
дубли заметок. Тот же приём, что и у бота Федерации.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, Request

from . import archive, config, telegram, text as textlib
from .transcribe import transcribe

log = logging.getLogger("notes")

router = APIRouter()

#: Типы вложений, из которых можно достать звук, в порядке предпочтения.
AUDIO_FIELDS = ("voice", "video_note", "audio")

#: Расширение для временного файла — от него зависит, как его прочитает
#: декодер. Кружок приезжает контейнером mp4, голосовое — ogg.
SUFFIX = {"voice": ".oga", "video_note": ".mp4", "audio": ".m4a"}

CALENDAR_WORDS = ("календар", "напомни", "встреч")


@router.post(config.WEBHOOK_PATH)
async def webhook(
    request: Request,
    secret: str = Header("", alias="X-Telegram-Bot-Api-Secret-Token"),
):
    if secret != config.WEBHOOK_SECRET:
        # 200, а не 403: Telegram на ошибку повторяет доставку, а повторять
        # здесь нечего — секрет не станет верным со второй попытки.
        return {"ok": True}

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    message = update.get("message") or update.get("edited_message")
    if isinstance(message, dict) and _from_owner(message):
        asyncio.create_task(_handle(message))

    return {"ok": True}


def _from_owner(message: dict[str, Any]) -> bool:
    sender = str((message.get("from") or {}).get("id", ""))
    return bool(config.OWNER_ID) and sender == config.OWNER_ID


async def _handle(message: dict[str, Any]) -> None:
    """Разобрать сообщение и ответить. Любая ошибка — в чат, а не в тишину."""
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    try:
        await _process(message, chat_id, message_id)
    except Exception as error:  # noqa: BLE001 — падать здесь нельзя
        log.exception("notes: обработка сообщения не удалась")
        try:
            await telegram.send_message(chat_id, f"Не получилось: {error}", message_id)
        except Exception:
            log.exception("notes: не удалось даже сообщить об ошибке")


async def _process(message: dict[str, Any], chat_id: int, message_id: int) -> None:
    kind, payload = _audio_of(message)
    caption = (message.get("caption") or message.get("text") or "").strip()

    if kind:
        duration = int(payload.get("duration") or 0)
        if duration > config.MAX_AUDIO_SECONDS:
            limit = config.MAX_AUDIO_SECONDS // 60
            await telegram.send_message(
                chat_id, f"Запись длиннее {limit} минут — не берусь.", message_id
            )
            return

        await telegram.send_message(chat_id, "Слушаю…", message_id)
        audio = await telegram.download_file(payload["file_id"])
        body = await transcribe(audio, SUFFIX.get(kind, ".oga"))
    elif caption:
        body, duration = caption, 0
    else:
        await telegram.send_message(
            chat_id, "Тут нечего расшифровывать: пришлите голосовое или текст.", message_id
        )
        return

    now = datetime.now()
    title = textlib.title_from(body) if body else textlib.title_from(caption)
    meta = _meta(message, caption if kind else "", duration)

    note = archive.render(title, body, now, meta)
    path = archive.note_path(now, textlib.slugify(title))
    url = await archive.save(path, note, f"заметка: {title}")

    reply = [body or "(тишина)"]
    if url:
        reply.append(f"\nСохранено: {path.rsplit('/', 1)[-1]}")
    elif config.archive_enabled():
        reply.append("\nВ архив не записалось — заметка только здесь.")

    if _wants_calendar(caption, body):
        when = textlib.parse_when(f"{caption} {body}", now)
        if when:
            link = textlib.calendar_link(title, when, body)
            reply.append(f"\n{when:%d.%m %H:%M} — в календарь:\n{link}")
        else:
            reply.append("\nДату не разобрал. Скажите «5 сентября 14:00» — пойму точно.")

    await telegram.send_message(chat_id, "\n".join(reply), message_id)


def _audio_of(message: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Найти звук в сообщении. Пересланное устроено так же, как своё."""
    for field in AUDIO_FIELDS:
        payload = message.get(field)
        if isinstance(payload, dict) and payload.get("file_id"):
            return field, payload

    document = message.get("document")
    if isinstance(document, dict) and str(document.get("mime_type", "")).startswith("audio/"):
        return "audio", document

    return "", {}


def _meta(message: dict[str, Any], caption: str, duration: int) -> dict[str, str]:
    """Обстоятельства заметки.

    У пересланного сохраняем автора и время исходного сообщения: через месяц
    это будет важнее самой расшифровки, а взять их будет неоткуда.
    """
    meta = {"Записано": datetime.now().strftime("%d.%m.%Y %H:%M")}
    if duration:
        meta["Длительность"] = f"{duration // 60}:{duration % 60:02d}"

    origin = message.get("forward_origin")
    author, sent = "", None
    if isinstance(origin, dict):
        kind = origin.get("type")
        if kind == "user":
            author = _name(origin.get("sender_user") or {})
        elif kind == "hidden_user":
            author = str(origin.get("sender_user_name") or "скрытый отправитель")
        elif kind in ("chat", "channel"):
            source = origin.get("chat") or origin.get("sender_chat") or {}
            author = str(source.get("title") or "канал")
        sent = origin.get("date")
    else:
        # Формат до Bot API 7.0 — на случай старого клиента или прокси.
        legacy = message.get("forward_from")
        if isinstance(legacy, dict):
            author = _name(legacy)
        elif message.get("forward_sender_name"):
            author = str(message["forward_sender_name"])
        sent = message.get("forward_date")

    if author:
        meta["Переслано от"] = author
    if sent:
        meta["Сказано"] = datetime.fromtimestamp(int(sent), timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    if caption:
        meta["Подпись"] = caption

    return meta


def _name(user: dict[str, Any]) -> str:
    parts = [str(user.get("first_name") or ""), str(user.get("last_name") or "")]
    name = " ".join(part for part in parts if part).strip()
    username = user.get("username")
    if username:
        name = f"{name} (@{username})".strip()
    return name or "неизвестно"


def _wants_calendar(caption: str, body: str) -> bool:
    """Календарь только по просьбе.

    Просьба ищется в подписи и в самой расшифровке: сказать «в календарь»
    голосом так же естественно, как подписать пересылку.
    """
    haystack = f"{caption} {body}".lower()
    return any(word in haystack for word in CALENDAR_WORDS)
