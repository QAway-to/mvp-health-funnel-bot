"""Почта как ключ от доступа: кому открываем, а кому нет.

Касса умеет ответить только «по этой почте платили» — не «сколько раз» и не
«кому». Значит, одну оплаченную почту может назвать кто угодно, кто её узнал,
а покупка при этом одна. Здесь проверяется, что второй раз она не сработает.
"""

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.funnel_store import UserState  # noqa: E402


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})
        return FakeMessage()


@pytest.fixture
def quiet_store(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.store, "event", noop)
    monkeypatch.setattr(bot_module.store, "save", noop)


@pytest.fixture
def buyer_and_stranger(monkeypatch, quiet_store):
    """Один заплатил и получил доступ, второй знает его почту."""
    buyer = UserState(chat_id="100", bucket="A", is_premium=True, email="buyer@example.com")
    stranger = UserState(chat_id="200", bucket="A")

    monkeypatch.setattr(bot_module.store, "all_users", lambda: [buyer, stranger])
    monkeypatch.setattr(
        bot_module.store, "user", lambda chat_id, **kw: buyer if chat_id == "100" else stranger
    )
    return buyer, stranger


@pytest.mark.asyncio
async def test_a_second_chat_cannot_reuse_a_paid_email(buyer_and_stranger, monkeypatch):
    granted = []
    monkeypatch.setattr(
        bot_module.TelegramBot, "_grant_premium",
        lambda self, chat_id, source, **kw: granted.append(chat_id),
    )
    message = FakeMessage()

    await bot_module.TelegramBot()._handle_email(message, "200", "buyer@example.com")

    assert granted == [], "чужая почта открыла доступ второму человеку"
    assert "уже открыт" in message.replies[0]["text"]


@pytest.mark.asyncio
async def test_case_does_not_get_around_it(buyer_and_stranger, monkeypatch):
    """В кассе адрес лежит как ввёл покупатель — сравнивать надо одинаково."""
    granted = []
    monkeypatch.setattr(
        bot_module.TelegramBot, "_grant_premium",
        lambda self, chat_id, source, **kw: granted.append(chat_id),
    )

    await bot_module.TelegramBot()._handle_email(FakeMessage(), "200", "BUYER@Example.COM")

    assert granted == []


@pytest.mark.asyncio
async def test_the_buyer_himself_is_not_locked_out(buyer_and_stranger):
    """Своя же почта не должна выглядеть занятой — это тот же человек."""
    message = FakeMessage()

    await bot_module.TelegramBot()._handle_email(message, "100", "buyer@example.com")

    text = message.replies[0]["text"]
    assert "другом чате" not in text, "покупателя заперли его же почтой"
    assert "и так открыт" in text


def test_a_free_user_does_not_hold_the_email(monkeypatch, quiet_store):
    """Занятой почта считается только там, где доступ реально открыт."""
    others = [UserState(chat_id="300", bucket="A", email="buyer@example.com")]
    monkeypatch.setattr(bot_module.store, "all_users", lambda: others)

    assert bot_module.TelegramBot()._chat_holding("buyer@example.com", besides="200") == ""
