"""Лендинги раздаются тем же процессом, что принимает вебхук.

Слитый сервис экономит счёт за хостинг, но создаёт риск, которого не было у
двух отдельных: catch-all маршрут сайта может перехватить адрес бота. Тогда
Telegram начнёт получать HTML вместо ответа, и узнаем мы об этом по тишине
в чатах.

Поэтому здесь проверяются две вещи: что сайт отдаётся правильно и что он не
съедает чужие адреса.
"""

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import site  # noqa: E402

built = pytest.mark.skipif(
    not site.is_available(),
    reason="статика не собрана: npm ci && npm run build в site/",
)


# --- маршруты бота остаются за ботом ----------------------------------------


def test_bot_routes_are_registered_before_the_catch_all():
    """FastAPI разбирает маршруты по порядку. Сайт обязан быть последним."""
    import main

    paths = [getattr(r, "path", "") for r in main.app.routes]
    catch_all = paths.index("/{url_path:path}")
    for path in ("/health", "/debug", "/tasks/followups", main.telegram_bot.WEBHOOK_PATH):
        assert paths.index(path) < catch_all, f"{path} перехватывается сайтом"


def test_catch_all_is_the_last_route():
    import main

    paths = [getattr(r, "path", "") for r in main.app.routes]
    assert paths[-1] == "/{url_path:path}", "после сайта появился ещё один маршрут"


# --- редиректы --------------------------------------------------------------


def test_old_slug_redirects_permanently():
    response = site.response_for("/samomassazh")
    assert response.status_code == 301
    assert response.headers["location"] == "/massazh/"


def test_ad_shortcuts_still_work():
    for source, target in (("/a", "/komfort/"), ("/b", "/sila/")):
        assert site.response_for(source).headers["location"] == target


def test_redirects_match_the_node_server():
    """Список продублирован в site/server.mjs. Разъедутся — часть ссылок умрёт."""
    server = (Path(__file__).resolve().parents[1] / "site" / "server.mjs").read_text(
        encoding="utf-8"
    )
    for source, target in site.REDIRECTS.items():
        assert f"['{source}', '{target}']" in server, f"в server.mjs нет {source} → {target}"


def test_redirects_carry_security_headers():
    response = site.response_for("/a")
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"


# --- отдача файлов ----------------------------------------------------------


@built
def test_root_serves_the_hub():
    assert site.response_for("/").status_code == 200


@built
def test_directory_urls_resolve_to_index():
    assert site.resolve("/zakalivanie/").name == "index.html"


@built
def test_precompressed_file_is_preferred():
    response = site.response_for("/", "br, gzip")
    assert response.headers["content-encoding"] == "br"
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.media_type == "text/html", "браузер предложит скачать файл"


@built
def test_compressed_html_keeps_one_charset():
    """Starlette дописывает charset сама: свой добавишь — получишь его дважды."""
    response = site.response_for("/", "br")
    assert response.headers["content-type"].count("charset") == 1


@built
def test_plain_file_when_the_browser_cannot_unpack():
    assert "content-encoding" not in site.response_for("/", "").headers


@built
def test_hashed_assets_are_cached_forever():
    asset = next(p for p in (site.DIST / "_astro").iterdir() if p.suffix == ".js")
    response = site.response_for(f"/_astro/{asset.name}")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@built
def test_html_is_never_cached():
    """HTML кэшировать нельзя: правка цены доедет до человека через сутки."""
    assert site.response_for("/").headers["cache-control"] == "no-cache"


@built
def test_unknown_page_gets_our_own_404():
    response = site.response_for("/такой-страницы-нет")
    assert response.status_code == 404
    assert response.path.name == "404.html", "отдана не наша страница"


@built
def test_path_traversal_is_refused():
    """Адрес с `..` не должен уводить за пределы сборки."""
    for attempt in ("/../../etc/passwd", "/../main.py", "/../../.env"):
        assert site.resolve(attempt) is None, f"{attempt} вышел наружу"


# --- сайта может не быть ----------------------------------------------------


def test_missing_build_does_not_break_the_bot(monkeypatch, tmp_path):
    """Контейнер без статики — не авария: бот обязан подняться и работать."""
    monkeypatch.setattr(site, "DIST", tmp_path / "nope")
    assert site.is_available() is False
    with pytest.raises(HTTPException) as caught:
        site.response_for("/")
    assert caught.value.status_code == 404


def test_redirects_work_without_a_build(monkeypatch, tmp_path):
    """Редирект не зависит от файлов — он должен пережить пустую сборку."""
    monkeypatch.setattr(site, "DIST", tmp_path / "nope")
    assert site.response_for("/a").status_code == 301
