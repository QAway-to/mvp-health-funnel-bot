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


# --- английская версия как законченный сайт, а не витрина -------------------
#
# До 03.09.2026 `/en/` была одностраничкой: карточки направлений не были
# ссылками, купить со страницы было нельзя, футер и `<html lang>` оставались
# русскими. Каждая проверка ниже закрывает одну из этих дыр — заметить их
# глазом можно только открыв английскую версию, а открывают её редко.

EN_PAGES = sorted(DIST.glob("en/**/index.html")) if DIST.is_dir() else []


def en_html(*parts: str) -> str:
    return (DIST.joinpath("en", *parts) / "index.html").read_text(encoding="utf-8")


def visible_text(html: str) -> str:
    """Текст без скриптов, стилей и тегов — то, что читает человек."""
    without_code = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", without_code)


def test_english_pages_declare_english():
    for page in EN_PAGES:
        html = page.read_text(encoding="utf-8")
        assert '<html lang="en">' in html, f"{page}: страница объявляет себя русской"
        assert 'content="en_US"' in html, f"{page}: og:locale остался русским"


def test_russian_pages_still_declare_russian():
    assert '<html lang="ru">' in (DIST / "index.html").read_text(encoding="utf-8")


def test_no_russian_text_on_english_pages():
    """Кириллица в англоязычной вёрстке читается как «собрано наспех»."""
    for page in EN_PAGES:
        text = visible_text(page.read_text(encoding="utf-8"))
        # Подпись переключателя — единственная законная кириллица: она
        # называет язык, на который уведёт, и по-английски была бы бесполезна.
        leftovers = [
            fragment
            for fragment in re.findall(r"[Ѐ-ӿ][Ѐ-ӿ\s,«»—-]{0,60}", text)
            if fragment.strip() != "Русский"
        ]
        assert not leftovers, f"{page.parent.name}: русский текст на английской странице: {leftovers}"


def test_direction_cards_on_the_english_home_are_links():
    """Карточка без ссылки — тупик там, где страница уже существует."""
    html = en_html()
    hrefs = re.findall(r'<a class="card" href="([^"]+)"', html)
    assert len(hrefs) == len(translated_paths()) - 1, f"карточек-ссылок {len(hrefs)}"
    built = built_pages()
    for href in hrefs:
        assert href.startswith("/en/"), f"карточка ведёт на русскую страницу: {href}"
        assert href in built, f"карточка ведёт в никуда: {href}"


def test_every_english_page_can_be_bought_from():
    """Цена без кнопки — это прайс-лист, а не предложение."""
    for page in EN_PAGES:
        html = page.read_text(encoding="utf-8")
        assert 'data-section="price"' in html, f"{page.parent.name}: нет блока подписки"
        assert "data-pay-open=" in html, f"{page.parent.name}: нет кнопки оплаты"
        assert "pay_card_" in html and "pay_stars_" in html, (
            f"{page.parent.name}: показана не вся оплата — карта и звёзды нужны обе"
        )


def test_prices_on_english_pages_are_in_english():
    for page in EN_PAGES:
        prices = re.findall(r'class="tier__price[^"]*"[^>]*>([^<]*)<', page.read_text(encoding="utf-8"))
        assert prices, f"{page.parent.name}: цены не показаны"
        for price in prices:
            assert "per month" in price, f"{page.parent.name}: цена «{price.strip()}»"


def test_the_language_warning_stands_next_to_the_price():
    """Узнать язык курса после оплаты — то же, что не узнать вовсе."""
    for page in EN_PAGES:
        html = page.read_text(encoding="utf-8")
        warning = html.find("subscription__warning")
        price = html.find('data-section="price"')
        assert warning != -1, f"{page.parent.name}: предупреждения о языке нет у цены"
        assert price < warning, f"{page.parent.name}: предупреждение вне блока цены"


def test_both_languages_promise_the_same_number_of_directions():
    """По-русски «десять направлений», по-английски «шесть» — разное предложение."""
    ru = (DIST / "index.html").read_text(encoding="utf-8")
    en = en_html()
    ru_soon = len(re.findall(r'class="soon__title[^"]*"', ru))
    en_soon = len(re.findall(r'class="soon__title[^"]*"', en))
    assert en_soon == ru_soon, f"готовятся: по-русски {ru_soon}, по-английски {en_soon}"


def test_english_pages_point_search_engines_at_both_versions():
    for page in EN_PAGES:
        html = page.read_text(encoding="utf-8")
        alternates = dict(re.findall(r'hreflang="([^"]+)" href="([^"]+)"', html))
        assert {"ru", "en", "x-default"} <= alternates.keys(), f"{page.parent.name}: {alternates}"
        assert alternates["x-default"] == alternates["ru"], "x-default должен вести на основную версию"


def test_the_logo_on_an_english_page_goes_to_the_english_home():
    """Логотип, уводящий на другой язык, работает переключателем — молча."""
    for page in EN_PAGES:
        html = page.read_text(encoding="utf-8")
        brand = re.search(r'<a class="header__brand"[^>]*href="([^"]+)"', html)
        assert brand and brand.group(1) == "/en/", f"{page.parent.name}: логотип ведёт на {brand}"
