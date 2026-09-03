"""Заголовок, адрес заметки и разбор дат для календаря.

Языковой модели здесь нет намеренно. Заголовок берётся первым предложением —
приём из `tools/tiktok_ingest.py`, где он работает на таких же расшифровках.
Даты разбираются правилами: «5 сентября 14:00» разбирается точно, а «напомни
как-нибудь на неделе» не разбирается никак — и это честнее, чем угадать.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import quote

MONTHS = {
    "января": 1, "январь": 1, "февраля": 2, "февраль": 2, "марта": 3, "март": 3,
    "апреля": 4, "апрель": 4, "мая": 5, "май": 5, "июня": 6, "июнь": 6,
    "июля": 7, "июль": 7, "августа": 8, "август": 8, "сентября": 9, "сентябрь": 9,
    "октября": 10, "октябрь": 10, "ноября": 11, "ноябрь": 11, "декабря": 12, "декабрь": 12,
}

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}


def title_from(text: str) -> str:
    """Первое предложение как заголовок — его всё равно править руками."""
    sentence = re.split(r"[.!?\n]", text.strip(), maxsplit=1)[0].strip()
    if not sentence:
        return "Без названия"
    return sentence[:70].rstrip() + "…" if len(sentence) > 70 else sentence


def slugify(title: str) -> str:
    """Латиница в имени файла: кириллица в путях репозитория живёт плохо."""
    lowered = title.lower()
    latin = "".join(TRANSLIT.get(char, char) for char in lowered)
    cleaned = re.sub(r"[^a-z0-9]+", "-", latin).strip("-")
    return (cleaned[:60].rstrip("-")) or "zametka"


# --- даты для календаря ------------------------------------------------------

TIME_RE = re.compile(r"\b(\d{1,2})[:.](\d{2})\b")
DAY_MONTH_RE = re.compile(r"\b(\d{1,2})\s+([а-яё]+)", re.IGNORECASE)
NUMERIC_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    """Найти дату и время. Не нашли — None, и это нормальный ответ.

    Понимает: «5 сентября 14:00», «05.09 14:00», «05.09.2026 9:30»,
    «завтра 8:00», «сегодня 18:30». Всё остальное честно не понимает.

    ДАТА ИЩЕТСЯ ПЕРВОЙ И ВЫРЕЗАЕТСЯ ИЗ СТРОКИ. Разделитель у даты и у времени
    один и тот же, и «05.09 9:30» без этого читается как время 05:09 —
    событие уезжало в пять утра. Поймано тестом, а не в переписке.
    """
    now = now or datetime.now()
    lowered = text.lower()

    day = month = year = None
    rest = lowered

    numeric = NUMERIC_RE.search(lowered)
    if numeric:
        day, month = int(numeric.group(1)), int(numeric.group(2))
        year = int(numeric.group(3) or now.year)
        if year < 100:
            year += 2000
        rest = lowered[: numeric.start()] + " " + lowered[numeric.end() :]
    else:
        named = DAY_MONTH_RE.search(lowered)
        # Только настоящий месяц: «30 утра» в «9:30 утра» иначе съело бы время.
        if named and named.group(2) in MONTHS:
            day, month, year = int(named.group(1)), MONTHS[named.group(2)], now.year
            rest = lowered[: named.start()] + " " + lowered[named.end() :]

    time_match = TIME_RE.search(rest)
    hour, minute = (int(time_match.group(1)), int(time_match.group(2))) if time_match else (9, 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    if day is not None:
        return _safe(year, month, day, hour, minute, now)

    if "послезавтра" in rest:
        return (now + timedelta(days=2)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if "завтра" in rest:
        return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if "сегодня" in rest:
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    return None


def _safe(year: int, month: int, day: int, hour: int, minute: int, now: datetime):
    """Собрать дату, отбросив несуществующую. Прошедшее в этом году — на следующий."""
    try:
        when = datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    # «5 сентября» в декабре означает следующий сентябрь, а не прошедший.
    if when < now - timedelta(days=1):
        try:
            when = when.replace(year=when.year + 1)
        except ValueError:
            return None
    return when


def calendar_link(title: str, when: datetime, details: str = "", hours: int = 1) -> str:
    """Ссылка, открывающая создание события с заполненными полями.

    Через ссылку, а не через API календаря: API требует доступа ко всему
    аккаунту и хранения токена, а экономит ровно одно нажатие.
    """
    end = when + timedelta(hours=hours)
    span = f"{when:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}"
    parts = [
        "action=TEMPLATE",
        f"text={quote(title[:200])}",
        f"dates={span}",
    ]
    if details:
        parts.append(f"details={quote(details[:900])}")
    return "https://calendar.google.com/calendar/render?" + "&".join(parts)
