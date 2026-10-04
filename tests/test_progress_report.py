"""Отчёт заказчику обязан сходиться сам с собой.

Этот файл читает заказчик рядом со своим планом и по нему принимает решения.
Предыдущая версия собиралась руками и разошлась с продуктом; значит проверять
надо именно то, что при ручной сборке и разъезжается.

Итоги считаются из статусов, а не пишутся рядом с ними. «Готово 5 из 39» и
строки, в которых готовых семь, — это не опечатка, это таблица, которой нельзя
верить ни в одной клетке.

Нумерация пунктов совпадает с планом, включая пропуски, и ни один номер не
встречается дважды. Заказчик ищет пункт по номеру; задвоенный номер означает,
что один из двух он не прочитает никогда.

Ни одна клетка «что сделано» и «что осталось» не пуста. Пустая клетка в отчёте
читается как «ничего» — а означает «забыли написать», и различить это со
стороны нельзя.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import progress_report as report  # noqa: E402

#: Номера пунктов плана. Пропуски в середине — в плане заказчика их тоже нет,
#: и выравнивать их нельзя: номер здесь это ссылка на его документ.
PLAN_NUMBERS = (
    "П1", "П2", "П3", "П4", "П5", "П6", "П7", "П8", "П9", "П10", "П11", "П12", "П13", "П14",
    "1", "2", "3", "4", "5", "6", "8", "9", "11", "12", "13", "14", "15", "16", "17", "18",
    "20", "21", "23", "25", "28", "30", "32", "33", "35",
)


def test_every_plan_item_is_present_exactly_once() -> None:
    assert tuple(item.number for item in report.ITEMS) == PLAN_NUMBERS


def test_totals_are_counted_from_the_statuses() -> None:
    numbers = report.totals()
    counts = numbers["counts"]

    assert numbers["total"] == len(report.ITEMS)
    assert sum(counts.values()) == len(report.ITEMS)
    assert counts[report.DONE] == sum(1 for i in report.ITEMS if i.status == report.DONE)


def test_average_matches_the_rows() -> None:
    expected = round(sum(item.readiness for item in report.ITEMS) / len(report.ITEMS))
    assert report.totals()["average"] == expected


@pytest.mark.parametrize("item", report.ITEMS, ids=[i.number for i in report.ITEMS])
def test_no_cell_is_left_empty(item: report.Item) -> None:
    assert item.plan and item.area and item.done and item.left and item.where
    assert item.changed, "колонка «что изменилось» заполняется всегда, хотя бы словом"
    assert 0 <= item.readiness <= 100


@pytest.mark.parametrize("item", report.ITEMS, ids=[i.number for i in report.ITEMS])
def test_status_matches_readiness(item: report.Item) -> None:
    """Статус и процент не имеют права противоречить друг другу.

    «Готово» на сорока процентах или «не начато» на восьмидесяти — это ровно та
    ошибка, которую в таблице не видно: глаз читает слово, решение принимается
    по проценту.
    """
    if item.status == report.DONE:
        assert item.readiness >= 75
    if item.status == report.NOT_STARTED:
        assert item.readiness <= 20
    if item.status == report.PARTIAL:
        # Проверка в обе стороны: «частично» на нуле — это «не начато», а
        # «частично» на сотне — «готово». И то и другое занижает или завышает
        # итог, который считается из этих же процентов.
        assert 1 <= item.readiness <= 99


def test_closed_by_decision_items_are_marked_done() -> None:
    """Пункты 17 и 20 сняты решениями заказчика — значит закрыты, а не висят.

    Пока они числятся незакрытыми, их считают незакрытой работой при оценке
    готовности, и оценка выходит ниже настоящей.
    """
    closed = {item.number: item for item in report.ITEMS if item.number in {"17", "20"}}
    assert set(closed) == {"17", "20"}
    for item in closed.values():
        assert item.status == report.DONE
        # Почему закрыт, должно быть написано в самой клетке: закрытый пункт без
        # объяснения выглядит как приписанный себе.
        assert "решени" in item.left


def test_the_file_is_written_and_has_every_sheet(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl", reason="сборка отчёта требует openpyxl")
    out = tmp_path / "отчёт.xlsx"

    report.build(out)

    book = openpyxl.load_workbook(out)
    assert book.sheetnames == ["Сводка", "Прогресс", "Вопросы аудитории", "Материалы", "Воронки"]
    # Шапка плюс строка на пункт — лист не должен терять пункты по дороге.
    assert book["Прогресс"].max_row == len(report.ITEMS) + 1
