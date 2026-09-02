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


# --- меню не должно возвращать в другой язык --------------------------------


def links_in_nav(html: str) -> list[str]:
    nav = re.search(r'<nav class="header__nav".*?</nav>', html, re.S)
    return re.findall(r'href="(/[^"#?]*)"', nav.group(0)) if nav else []


def test_the_menu_on_an_english_page_stays_in_english():
    """Переключился на английский, открыл меню — и уехал обратно на русский."""
    for page in (DIST / "en").glob("*/index.html"):
        for href in links_in_nav(page.read_text(encoding="utf-8")):
            assert href.startswith("/en/"), f"{page.parent.name}: меню ведёт на {href}"


def test_the_menu_on_a_russian_page_stays_in_russian():
    for name in ("son", "massazh", "zakalivanie"):
        for href in links_in_nav((DIST / name / "index.html").read_text(encoding="utf-8")):
            assert not href.startswith("/en/"), f"{name}: меню ведёт на {href}"


def test_english_pages_are_not_labelled_in_russian():
    html = (DIST / "en" / "son" / "index.html").read_text(encoding="utf-8")
    nav = re.search(r'<nav class="header__nav".*?</nav>', html, re.S).group(0)
    assert not re.search(r"[Ѐ-ӿ]", nav), "в английском меню кириллица"


def test_step_counts_match_the_real_courses():
    """Обещать в английской версии другое число шагов — продать другое."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from utils.steps import load_courses

    courses = load_courses()
    for page in (DIST / "en").glob("*/index.html"):
        slug = page.parent.name
        course = courses.get(slug)
        if course is None:
            continue
        shown = page.read_text(encoding="utf-8").count('class="dir__step"')
        assert shown == len(course.steps), f"{slug}: показано {shown}, в курсе {len(course.steps)}"
