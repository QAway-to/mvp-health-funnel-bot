"""Расшифровка голосовых: сначала облако, и только при неудаче — локально.

ПОЧЕМУ ПУТЕЙ ДВА. Локально в этот инстанс влезает `base` — 74 миллиона
параметров. На русском такая модель не столько ошибается в буквах, сколько
подставляет вместо неуслышанного слова похожее по звучанию, и заметка выходит
связной на вид и неверной по сути. Ширина луча этого не чинит: луч ищет лучший
путь по той же модели, которая нужного слова просто не знает.

Поэтому расшифровка ушла в Groq, к `whisper-large-v3` — это в двадцать раз
больше параметров и другой класс точности на русском. Заодно освободилось
ядро: пока считалась заметка, бот Федерации отвечал покупателям медленнее.

Локальная модель осталась запасным путём. Облако может не ответить, ключ может
протухнуть, тариф — закончиться, и во всех этих случаях кривая расшифровка
полезнее извинений. Переход происходит молча для владельца и с записью в лог.

ДВЕ ВЕЩИ, БЕЗ КОТОРЫХ ЛОКАЛЬНЫЙ ПУТЬ УРОНИЛ БЫ СЕРВИС.

Первая: расшифровка считается в отдельном потоке. Она занимает процессор
секундами и минутами, а в этом же процессе живёт вебхук бота Федерации —
посчитай мы в цикле событий, покупатели ждали бы ответа всё это время.

Вторая: одновременно считается ровно одна запись. Ядро одно, и две модели на
нём не ускорят ни одну, зато удвоят память. Вторая заметка ждёт своей очереди.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

import aiohttp

from . import config

log = logging.getLogger("notes")

#: Groq говорит на диалекте OpenAI, отсюда и форма адреса.
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

#: Три минуты. Считает Groq быстрее записи в разы, и столько времени уходит не
#: на расшифровку, а на загрузку файла с этого инстанса.
TIMEOUT = aiohttp.ClientTimeout(total=180)

#: Модель загружается один раз и живёт до перезапуска: её подъём с диска —
#: единицы секунд, и платить их на каждой заметке незачем.
#:
#: Тип намеренно `Any`: `WhisperModel` приезжает из faster_whisper, а тот
#: тянет за собой ctranslate2 и onnxruntime на сотни мегабайт. Импортировать
#: их ради аннотации в модуле, который на облачном пути к ним не обращается,
#: значит платить памятью за подсказку редактору.
_model: Any = None

#: Очередь на одного. Не про корректность, а про память и отзывчивость.
_lock = asyncio.Lock()


async def transcribe(audio: bytes, suffix: str = ".oga") -> str:
    """Расшифровать запись. Пустая строка означает тишину, а не ошибку."""
    if config.remote_transcription_enabled():
        text = await _remote(audio, suffix)
        # Именно `is not None`: пустая строка — это тишина, законный ответ
        # облака, и переспрашивать её у слабой локальной модели незачем.
        if text is not None:
            log.info("notes: расшифровано в облаке, %s символов", len(text))
            return text
    else:
        # Ключа нет — это не поломка, но и не то, чего мы хотели. Без этой
        # строки «облако включено» и «облако не настроено» выглядят в логах
        # одинаково: тишиной.
        log.warning("notes: ключ Groq не задан — считаю локально")

    return await _local(audio, suffix)


async def _remote(audio: bytes, suffix: str) -> str | None:
    """Расшифровать в облаке. `None` — «не вышло, считайте сами»."""
    if len(audio) > config.GROQ_MAX_BYTES:
        log.warning(
            "notes: запись %.1f МБ не пролезет в Groq — считаю локально",
            len(audio) / 1024 / 1024,
        )
        return None

    form = aiohttp.FormData()
    # Имя файла не декоративное: по расширению на той стороне выбирают
    # разборщик контейнера. Голосовое приезжает ogg, кружок — mp4.
    form.add_field("file", audio, filename=f"note{suffix}", content_type="application/octet-stream")
    form.add_field("model", config.GROQ_MODEL)
    form.add_field("language", "ru")
    form.add_field("response_format", "json")
    # Ноль — без перебора температур. Whisper поднимает её сам, когда кусок не
    # разобрался, и на большой модели это чаще выдумывает, чем спасает.
    form.add_field("temperature", "0")

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                GROQ_URL,
                data=form,
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            ) as response:
                if response.status == 401:
                    # Самая вероятная причина здесь — ключ от xAI вместо Groq.
                    # Имена похожи до неразличимости, и без этой строки искать
                    # причину пришлось бы в аудиофайле.
                    log.error(
                        "notes: Groq не принял ключ (401). Ключи Groq начинаются "
                        "на gsk_; если в переменной лежит xai-… — это ключ xAI, "
                        "а у него распознавания речи нет. Считаю локально."
                    )
                    return None
                if response.status != 200:
                    log.error(
                        "notes: Groq ответил %s: %s — считаю локально",
                        response.status,
                        (await response.text())[:300],
                    )
                    return None
                data = await response.json()

                # Разбор ответа тоже внутри try, и это не педантизм. Двести с
                # телом не той формы приходит не от Groq, а от того, кто встал
                # между нами: заглушка прокси, страница лимита. `data` тогда
                # список или строка, `.get` по ней падает, и заметка умерла бы
                # с исключением ровно там, где весь этот путь был затеян ради
                # обратного — тихо уйти на локальную модель.
                if not isinstance(data, dict):
                    log.error(
                        "notes: Groq ответил не объектом, а %s — считаю локально",
                        type(data).__name__,
                    )
                    return None

                return str(data.get("text") or "").strip()
    except Exception:  # noqa: BLE001 — сеть падает как угодно, ответ один
        log.exception("notes: запрос к Groq не удался — считаю локально")
        return None


def _load() -> Any:
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
        beam_size=config.BEAM_SIZE,
        # ЗАТРАВКИ ЗДЕСЬ НЕТ И БЫТЬ НЕ ДОЛЖНО. Идея показать декодеру образец
        # речи со знакомыми словами выглядит здравой, но на маленькой модели
        # даёт обратное: она начинает вставлять слова из самой затравки туда,
        # где их не произносили. Ошибка при этом выглядит увереннее прежней.
        vad_filter=True,
        vad_parameters={
            # Отсечение тишины режет по краям речи, и на коротких фразах это
            # съедает первый и последний слог. Поля шире стандартных 400 мс —
            # лишняя треть секунды тишины расшифровке не мешает, а обрубленное
            # начало слова портит всю фразу.
            "speech_pad_ms": 700,
            # Порог ниже стандартного 0.5: на диктофонной записи с телефона
            # тихий слог в конце слова не дотягивает до половины и пропадает
            # вместе с окончанием. Цена — лишняя секунда шума на входе.
            "threshold": 0.35,
        },
        # Оставлено выключенным намеренно: с включённым Whisper цепляется за
        # собственный предыдущий вывод и уходит в повтор одной фразы до конца
        # записи. Для монолога на несколько минут это дороже, чем потеря
        # связности между кусками.
        condition_on_previous_text=False,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


async def _local(audio: bytes, suffix: str) -> str:
    # Модель резидентна, и на инстансе с потолком по памяти это самая дорогая
    # строка во всём модуле. В лог — чтобы OOM было с чем сопоставить.
    log.info("notes: считаю локально моделью %s, луч %s", config.WHISPER_MODEL, config.BEAM_SIZE)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(audio)
        temp = Path(handle.name)

    try:
        async with _lock:
            # to_thread, а не прямой вызов: см. заголовок модуля.
            return await asyncio.to_thread(_run, str(temp))
    finally:
        temp.unlink(missing_ok=True)
