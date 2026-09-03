"""Заметки в отдельный репозиторий GitHub.

ПОЧЕМУ РЕПОЗИТОРИЙ, А НЕ БАЗА. Заметку нужно уметь попросить словами —
«прочитай про монетизацию». По файлам это обычный поиск, у каждой заметки
настоящий адрес, а правки видны историей. Базы для этого пришлось бы заводить,
поднимать и бэкапить.

ПОЧЕМУ ОТДЕЛЬНЫЙ. У сервиса автодеплой с пуша: складывай мы заметки сюда же,
каждая надиктованная мысль пересобирала бы прод.

Имя файла — дата, время и заголовок латиницей. Сортировка по имени сразу даёт
порядок от старых к новым, поэтому отдельный указатель не нужен: «последние
три» — это три последних файла в каталоге.
"""

from __future__ import annotations

import base64
from datetime import datetime

import aiohttp

from . import config

API = "https://api.github.com"
TIMEOUT = aiohttp.ClientTimeout(total=30)


def note_path(when: datetime, slug: str) -> str:
    return f"notes/{when:%Y-%m-%d-%H%M}-{slug}.md"


def render(title: str, body: str, when: datetime, meta: dict[str, str]) -> str:
    """Заметка одним файлом: заголовок, обстоятельства, текст.

    Обстоятельства нужны у пересланного: через месяц «кто это сказал и когда»
    важнее самой расшифровки, а восстановить их будет неоткуда.
    """
    lines = [f"# {title}", ""]
    for key, value in meta.items():
        if value:
            lines.append(f"- **{key}:** {value}")
    lines += ["", body.strip() or "_(тишина)_", ""]
    return "\n".join(lines)


async def save(path: str, content: str, message: str) -> str | None:
    """Положить файл в репозиторий. Возвращает адрес или None, если не вышло.

    Ошибка здесь не должна стоить человеку заметки: текст он уже получил в
    чат, поэтому наверх уходит None, а не исключение.
    """
    if not config.archive_enabled():
        return None

    url = f"{API}/repos/{config.ARCHIVE_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    headers = {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.put(url, json=payload, headers=headers) as response:
            if response.status not in (200, 201):
                return None
            data = await response.json()

    return (data.get("content") or {}).get("html_url")
