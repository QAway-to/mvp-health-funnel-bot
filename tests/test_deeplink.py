"""Разбор метки из deep link.

Метка приезжает из адресной строки, то есть от кого угодно. Здесь проверяется
ровно два свойства: уровень признаётся только свой, а всё непонятное уходит в
безобидное поле направления, а не в покупку.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.deeplink import parse_start_payload  # noqa: E402

PLANS = frozenset({"buy_base", "buy_premium", "buy_pro"})


def test_plan_and_direction_are_split():
    assert parse_start_payload("buy_base__son", PLANS) == ("buy_base", "son")


def test_direction_with_a_hyphen_survives():
    """Дефис живёт внутри направлений — разделителем он быть не может."""
    assert parse_start_payload("buy_premium__vrednye-privychki", PLANS) == (
        "buy_premium",
        "vrednye-privychki",
    )


def test_plan_without_direction():
    assert parse_start_payload("buy_pro", PLANS) == ("buy_pro", "")


def test_plain_direction_stays_a_direction():
    """Старые ссылки продолжают работать — их разошлось уже немало."""
    assert parse_start_payload("zakalivanie", PLANS) == ("", "zakalivanie")


def test_unknown_plan_does_not_become_a_purchase():
    """Чужая метка не должна открывать оплату уровня, которого у нас нет."""
    assert parse_start_payload("buy_free__son", PLANS) == ("", "buy_free__son")


def test_empty_payload():
    assert parse_start_payload("", PLANS) == ("", "")
    assert parse_start_payload("   ", PLANS) == ("", "")
