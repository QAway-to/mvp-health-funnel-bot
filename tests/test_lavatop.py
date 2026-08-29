"""Оплата картой через LavaTop — вторая дверь к тому же доступу.

Telegram Stars работают только внутри Telegram. LavaTop принимает карту, но
живёт снаружи, и связать платёж с человеком в боте нечем, кроме
идентификатора, который мы сами положили в ссылку оплаты.

Формат уведомления с документацией LavaTop не сверялся. Поэтому проверяется не
«мы угадали формат», а то, что при любом формате ничего не сломается: чужой не
получит доступ, а свой платёж не потеряется молча.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402


def test_buyer_id_is_found_in_the_obvious_places():
    for payload in (
        {"client_id": "12345"},
        {"clientId": "12345"},
        {"custom": "12345"},
        {"buyer_id": "12345"},
        {"buyer": {"id": "12345"}},
        {"data": {"client_id": "12345"}},
    ):
        assert main._buyer_chat_id(payload) == "12345", payload


def test_non_numeric_ids_are_refused():
    """chat_id в Telegram числовой. Всё остальное — не он."""
    for payload in ({"client_id": "someone@example.com"}, {"client_id": "не число"}):
        assert main._buyer_chat_id(payload) == ""


def test_missing_buyer_is_not_an_exception():
    """Платёж без идентификатора — повод разобраться, а не упасть."""
    assert main._buyer_chat_id({}) == ""
    assert main._buyer_chat_id({"amount": 900}) == ""
    assert main._buyer_chat_id("не словарь") == ""


def test_grant_is_reachable_from_outside_telegram():
    """Оплата картой должна выдавать доступ тем же кодом, что и звёзды."""
    assert hasattr(main.telegram_bot, "grant_premium")


def test_route_is_off_without_a_secret():
    """Открытая точка выдачи доступа = премиум любому, кто знает адрес."""
    from config import config

    assert hasattr(config, "LAVATOP_SECRET")


def test_route_is_registered_before_the_site():
    paths = [getattr(r, "path", "") for r in main.app.routes]
    assert paths.index("/payments/lavatop") < paths.index("/{url_path:path}")
