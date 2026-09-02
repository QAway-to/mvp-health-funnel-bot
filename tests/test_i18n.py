"""Переключатель языка: ведёт ли он туда, где что-то есть.

Список переведённых страниц уже разошёлся с тем, что собирается: в него были
вписаны адреса, которых нет, и переключатель вёл на 404 — ровно туда, от чего
он должен спасать. Здесь это проверяется сборкой, а не вниманием.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1] / "site"
DIST = ROOT / "dist"
I18N = ROOT / "src" / "i18n" / "index.ts"

pytestmark = pytest.mark.skipif(not DIST.is_dir(), reason="сайт не собран")

SWITCH = re.compile(r'class="header__lang"[^>]*href="([^"]+)"')


def translated_paths() -> list[str]:
    source = I18N.read_text(encoding="utf-8")
    block = source.split("TRANSLATED_PATHS = [")[1].split("]")[0]
    return re.findall(r"'([^']+)'", block)


def built_pages() -> set[str]:
    """Адреса собранных страниц: dist/en/index.html → /en/."""
    pages = set()
    for path in DIST.rglob("index.html"):
        rel = path.relative_to(DIST).parent.as_posix()
        pages.add("/" if rel == "." else f"/{rel}/")
    return pages


def test_every_declared_translation_exists():
    built = built_pages()
    for path in translated_paths():
        expected = "/en/" if path == "/" else f"/en{path}"
        assert expected in built, f"объявлен перевод {path}, а страницы {expected} нет"


def test_the_switcher_never_points_at_a_missing_page():
    built = built_pages()
    missing = []
    for page in DIST.rglob("index.html"):
        found = SWITCH.search(page.read_text(encoding="utf-8"))
        if found and found.group(1) not in built:
            missing.append((page.relative_to(DIST).as_posix(), found.group(1)))
    assert not missing, f"переключатель ведёт в никуда: {missing}"


def test_the_switcher_is_on_every_page():
    """Пропадающий переключатель читается как «языка просто нет»."""
    without = [
        page.relative_to(DIST).as_posix()
        for page in DIST.rglob("index.html")
        if not SWITCH.search(page.read_text(encoding="utf-8"))
    ]
    assert not without, f"страницы без переключателя: {without}"


def test_the_english_page_does_not_promise_a_translated_course():
    """Продать англоязычному человеку русский курс молча — тот же обман."""
    html = (DIST / "en" / "index.html").read_text(encoding="utf-8")
    assert "material is in Russian" in html


def test_switch_back_from_english_lands_on_the_russian_home():
    html = (DIST / "en" / "index.html").read_text(encoding="utf-8")
    assert SWITCH.search(html).group(1) == "/"
