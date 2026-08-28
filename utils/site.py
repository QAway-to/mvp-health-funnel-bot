"""Раздача лендингов тем же процессом, что принимает вебхук Telegram.

Зачем так. На Render тариф привязан к сервису, и два сервиса — это два счёта.
При этом засыпание на бесплатном тарифе бьёт по обоим: посетитель лендинга
ждёт холодного старта, а человек, написавший боту первым сообщением, ждёт
30–50 секунд ответа. Один платный сервис закрывает обе проблемы разом, но
только если сервис действительно один.

Раньше сайт отдавал отдельный Node-процесс (`site/server.mjs`, sirv). Здесь
повторено то же поведение: заранее сжатые `.br` и `.gz`, вечный кэш для
хешированных ассетов, `no-cache` для HTML, те же заголовки безопасности и тот
же список редиректов. Файл `server.mjs` остаётся в репозитории до переезда —
пока сайт живёт отдельным сервисом, отдаёт именно он.

Статики может не быть вовсе: контейнер собран без Node или сборка не
запускалась. Это не авария — бот обязан подняться и работать, а сайт в таком
случае просто не отдаётся.
"""

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response

from utils.logger import log_agent_action

#: Куда Astro кладёт сборку. Путь относительно корня репозитория.
DIST = Path(__file__).resolve().parents[1] / "site" / "dist"

#: Хешированные ассеты и картинки кэшируются навсегда, HTML — никогда:
#: иначе правка цены доедет до человека через сутки.
IMMUTABLE_PREFIXES = ("/_astro/", "/img/")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Страницы не должны открываться во фрейме на чужом домене.
    "X-Frame-Options": "SAMEORIGIN",
}

#: Список синхронен с REDIRECTS в site/server.mjs. Пока живут оба, правки
#: нужны в обоих местах: разъедутся — часть ссылок отдаст 404, и заметит это
#: реклама, а не разработчик.
REDIRECTS = {
    "/beg": "/beg/",
    "/komfort": "/komfort/",
    "/sila": "/sila/",
    "/son": "/son/",
    "/zaryadka": "/zaryadka/",
    "/massazh": "/massazh/",
    "/zakalivanie": "/zakalivanie/",
    "/vrednye-privychki": "/vrednye-privychki/",
    "/start": "/start/",
    "/demo": "/demo/",
    # Самомассаж слит с массажем 28.08.2026: страницы больше нет, ссылки на
    # неё разошлись.
    "/samomassazh": "/massazh/",
    "/samomassazh/": "/massazh/",
    # Короткие ссылки для рекламных кампаний.
    "/a": "/komfort/",
    "/b": "/sila/",
    # Прежние слаги сегмента: сначала «без боли», потом «без дискомфорта».
    "/bez-boli": "/komfort/",
    "/bez-boli/": "/komfort/",
    "/bez-diskomforta": "/komfort/",
    "/bez-diskomforta/": "/komfort/",
}

#: Кодировки по убыванию предпочтения: brotli сжимает лучше gzip.
ENCODINGS = (("br", ".br"), ("gzip", ".gz"))


def is_available() -> bool:
    """Собрана ли статика. Пустая папка — рабочее состояние, а не поломка."""
    return DIST.is_dir() and (DIST / "index.html").is_file()


def resolve(url_path: str) -> Path | None:
    """Файл, который отдаём по этому адресу, или None.

    Адрес со слешем — это папка со своим `index.html`: Astro собирает
    многостраничник именно так. Выход за пределы `dist` отсекается: путь с
    `..` в адресе иначе увёл бы наружу.
    """
    relative = url_path.lstrip("/")
    candidate = (DIST / relative).resolve() if relative else DIST.resolve()

    try:
        candidate.relative_to(DIST.resolve())
    except ValueError:
        return None

    if candidate.is_dir():
        candidate = candidate / "index.html"
    if candidate.is_file():
        return candidate
    return None


def _cache_control(url_path: str) -> str:
    if any(url_path.startswith(prefix) for prefix in IMMUTABLE_PREFIXES):
        return "public, max-age=31536000, immutable"
    return "no-cache"


def _precompressed(path: Path, accept_encoding: str) -> tuple[Path, str] | None:
    """Готовый `.br` или `.gz`, если браузер его примет.

    Сжимать на лету не нужно: `npm run build` уже положил сжатые копии рядом.
    """
    accepted = accept_encoding.lower()
    for name, suffix in ENCODINGS:
        if name not in accepted:
            continue
        packed = path.with_name(path.name + suffix)
        if packed.is_file():
            return packed, name
    return None


def response_for(url_path: str, accept_encoding: str = "") -> Response:
    """Ответ лендинга: редирект, файл или 404 с нашей же страницей."""
    target = REDIRECTS.get(url_path)
    if target:
        return RedirectResponse(target, status_code=301, headers=SECURITY_HEADERS)

    if not is_available():
        raise HTTPException(status_code=404, detail="site is not built")

    path = resolve(url_path)
    if path is None:
        not_found = DIST / "404.html"
        if not_found.is_file():
            return FileResponse(
                not_found,
                status_code=404,
                media_type="text/html",
                headers={**SECURITY_HEADERS, "Cache-Control": "no-cache"},
            )
        raise HTTPException(status_code=404, detail="not found")

    headers = {**SECURITY_HEADERS, "Cache-Control": _cache_control(url_path)}
    media_type = None

    packed = _precompressed(path, accept_encoding)
    if packed:
        path, encoding = packed
        headers["Content-Encoding"] = encoding
        # Кэши обязаны различать сжатый и несжатый ответ по одному адресу.
        headers["Vary"] = "Accept-Encoding"
        # Тип берём у исходного файла: у `.br` расширение своё, и без этого
        # браузер получил бы application/octet-stream и предложил скачать.
        media_type = _media_type(path.name.rsplit(".", 1)[0])

    return FileResponse(path, headers=headers, media_type=media_type)


# Без charset: Starlette сама допишет его к text/*, а если написать здесь,
# в заголовке окажется «charset=utf-8; charset=utf-8».
_MEDIA_TYPES = {
    "html": "text/html",
    "css": "text/css",
    "js": "text/javascript",
    "xml": "application/xml",
    "txt": "text/plain",
    "json": "application/json",
    "svg": "image/svg+xml",
}


def _media_type(filename: str) -> str | None:
    return _MEDIA_TYPES.get(filename.rsplit(".", 1)[-1].lower())


def log_state() -> None:
    """Сказать при старте, отдаётся сайт или нет. Молчание тут дороже строки."""
    if is_available():
        pages = len(list(DIST.rglob("index.html")))
        log_agent_action("Site", f"Лендинги отдаются этим же сервисом: страниц — {pages}")
    else:
        log_agent_action(
            "Site",
            f"Статики нет ({DIST}) — сайт не отдаётся, бот работает как обычно",
            level="WARNING",
        )
