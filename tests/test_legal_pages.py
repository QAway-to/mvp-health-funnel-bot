"""Оферта и политика: пока реквизитов нет, документа нет.

Оферта с дырой на месте названия компании хуже её отсутствия. Отсутствующую
видно сразу; дырявую человек читает как настоящую, и в спорной ситуации она
работает против того, кто её выложил.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DIST = Path(__file__).resolve().parents[1] / "site" / "dist"
LEGAL = Path(__file__).resolve().parents[1] / "site" / "src" / "content" / "legal.ts"

pytestmark = pytest.mark.skipif(not DIST.is_dir(), reason="сайт не собран")


def page(name: str) -> str:
    return (DIST / name / "index.html").read_text(encoding="utf-8")


def body(html: str) -> str:
    """Только тело: в <head> лежит описание страницы, и оно не документ."""
    start = html.find("<body")
    return html[start:] if start > 0 else html


def requisites_filled() -> bool:
    source = LEGAL.read_text(encoding="utf-8")
    block = source.split("export const requisites")[1].split("} as const")[0]
    return "''" not in block


def test_both_pages_exist():
    for name in ("oferta", "politika"):
        assert (DIST / name / "index.html").is_file(), name


@pytest.mark.skipif(requisites_filled(), reason="реквизиты заполнены — документ показывается")
def test_the_document_is_not_shown_without_requisites():
    for name in ("oferta", "politika"):
        text = body(page(name))
        assert "готовится" in text, f"{name}: нет честной заглушки"
        assert "1. Общие положения" not in text, f"{name}: оферта показана без реквизитов"
        assert "1. Какие данные мы получаем" not in text, f"{name}: политика показана без реквизитов"


@pytest.mark.skipif(requisites_filled(), reason="реквизиты заполнены — ссылки уместны")
def test_the_footer_does_not_link_to_a_document_that_is_not_there():
    home = body(page("son"))
    assert "/oferta/" not in home, "подвал ведёт на неопубликованный документ"
    assert "/politika/" not in home


def test_the_pending_notice_says_sales_are_not_open():
    """Иначе человек решит, что можно платить, а условий просто нет."""
    if requisites_filled():
        pytest.skip("документ опубликован")
    assert "оплата на сайте не принимается" in body(page("oferta"))
