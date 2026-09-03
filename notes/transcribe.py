"""Расшифровка голосовых — локально, тем же способом, что и ролики проекта.

Вызов Whisper здесь слово в слово такой же, как в `tools/tiktok_ingest.py`:
модель на CPU в int8, русский язык, отсечение тишины, beam_size=1. Расходиться
им незачем — это одна и та же задача на одном и том же железе.

ДВЕ ВЕЩИ, БЕЗ КОТОРЫХ ЭТО УРОНИЛО БЫ СЕРВИС.

Первая: расшифровка считается в отдельном потоке. Она занимает процессор
секундами и минутами, а в этом же процессе живёт вебхук бота Федерации —
посчитай мы в цикле событий, покупатели ждали бы ответа всё это время.

Вторая: одновременно считается ровно одна запись. Ядро одно, и две модели на
нём не ускорят ни одну, зато удвоят память. Вторая заметка ждёт своей очереди.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from . import config

#: Модель загружается один раз и живёт до перезапуска: её подъём с диска —
#: единицы секунд, и платить их на каждой заметке незачем.
_model = None

#: Очередь на одного. Не про корректность, а про память и отзывчивость.
_lock = asyncio.Lock()


def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def _run(path: str) -> str:
    model = _load()
    segments, _info = model.transcribe(
        path,
        language="ru",
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


async def transcribe(audio: bytes, suffix: str = ".oga") -> str:
    """Расшифровать запись. Пустая строка означает тишину, а не ошибку."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(audio)
        temp = Path(handle.name)

    try:
        async with _lock:
            # to_thread, а не прямой вызов: см. заголовок модуля.
            return await asyncio.to_thread(_run, str(temp))
    finally:
        temp.unlink(missing_ok=True)
