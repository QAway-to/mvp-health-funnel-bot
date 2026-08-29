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


# --- чем касса подписывает уведомление --------------------------------------
#
# В её спецификации два способа, и какой окажется в кабинете — заранее не
# известно. Не поддержать один значит упереться в форму настройки.


class _FakeRequest:
    def __init__(self, headers=None, params=None):
        self.headers = headers or {}
        self.query_params = params or {}


def _with_secret(monkeypatch, value="s3cret"):
    monkeypatch.setattr(main.config, "LAVATOP_SECRET", value)
    return value


def test_api_key_header_is_accepted(monkeypatch):
    secret = _with_secret(monkeypatch)
    assert main._webhook_is_ours(_FakeRequest(headers={"X-Api-Key": secret}))


def test_query_key_is_accepted(monkeypatch):
    secret = _with_secret(monkeypatch)
    assert main._webhook_is_ours(_FakeRequest(params={"key": secret}))


def test_basic_auth_pair_is_accepted(monkeypatch):
    import base64

    _with_secret(monkeypatch, "lava:s3cret")
    token = base64.b64encode(b"lava:s3cret").decode()
    assert main._webhook_is_ours(_FakeRequest(headers={"Authorization": f"Basic {token}"}))


def test_basic_auth_password_alone_is_accepted(monkeypatch):
    """В форме кабинета бывает и пара, и один пароль — угадывать не будем."""
    import base64

    _with_secret(monkeypatch, "s3cret")
    token = base64.b64encode(b"lava:s3cret").decode()
    assert main._webhook_is_ours(_FakeRequest(headers={"Authorization": f"Basic {token}"}))


def test_a_wrong_secret_is_refused(monkeypatch):
    _with_secret(monkeypatch)
    assert not main._webhook_is_ours(_FakeRequest(headers={"X-Api-Key": "чужой"}))


def test_no_secret_at_all_is_refused(monkeypatch):
    _with_secret(monkeypatch)
    assert not main._webhook_is_ours(_FakeRequest())


def test_broken_basic_header_does_not_raise(monkeypatch):
    """Мусор в заголовке — отказ, а не пятисотка посреди приёма платежа."""
    _with_secret(monkeypatch)
    assert not main._webhook_is_ours(_FakeRequest(headers={"Authorization": "Basic не-base64!"}))
