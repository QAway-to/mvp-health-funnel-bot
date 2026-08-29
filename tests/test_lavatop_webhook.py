"""Кому вебхук кассы открывает доступ, а кому нет.

Здесь два риска, и оба дорогие. Открыть доступ по неудачной оплате — раздать
продукт: уведомление о провале приходит тем же адресом, с тем же покупателем,
и отличается только статусом. Не открыть по удачной — человек заплатил и не
получил ничего, а узнаем мы об этом от него.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402

SUCCESS = {
    "eventType": "payment.success",
    "product": {"id": "p1", "title": "Подписка"},
    "buyer": {"email": "Buyer@Example.com"},
    "contractId": "c1",
    "status": "completed",
    "clientUtm": {"utm_source": "telegram", "utm_content": "7069863028"},
}


def test_successful_payment_is_recognised():
    assert main._is_paid(SUCCESS)


def test_failed_payment_is_refused():
    """Тот же покупатель, тот же продукт — разница только в статусе."""
    failed = {**SUCCESS, "eventType": "payment.failed", "status": "failed"}
    assert not main._is_paid(failed)


def test_recurring_charge_extends_access():
    charge = {**SUCCESS, "eventType": "subscription.recurring.payment.success"}
    assert main._is_paid(charge)


def test_unknown_shape_is_refused():
    """Пустое уведомление не должно читаться как оплата."""
    for payload in ({}, {"hello": "world"}, None, []):
        assert not main._is_paid(payload)


def test_chat_comes_from_the_label_the_bot_put_in_the_invoice():
    assert main._buyer_chat_id(SUCCESS) == "7069863028"


def test_storefront_payment_has_no_label():
    """С витрины метки нет — остаётся почта."""
    storefront = {k: v for k, v in SUCCESS.items() if k != "clientUtm"}
    assert main._buyer_chat_id(storefront) == ""
    assert main._buyer_email(storefront) == "buyer@example.com"


def test_email_is_lowercased_for_comparison():
    """В кассе адрес лежит как ввёл покупатель, у нас — как он написал боту."""
    assert main._buyer_email(SUCCESS) == "buyer@example.com"


def test_email_lookup_finds_the_chat(monkeypatch):
    from utils.funnel_store import UserState

    users = [
        UserState(chat_id="111", bucket="A", email="someone@else.com"),
        UserState(chat_id="222", bucket="A", email="BUYER@example.com"),
    ]
    monkeypatch.setattr(main.store, "all_users", lambda: users)
    assert main._chat_by_email(SUCCESS) == "222"


def test_email_lookup_without_a_match(monkeypatch):
    monkeypatch.setattr(main.store, "all_users", lambda: [])
    assert main._chat_by_email(SUCCESS) == ""
