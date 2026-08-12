"""Клик по офферу не должен отдавать ссылку на оплату, пока оффер не настроен.

Кнопка может пережить перезапуск: инлайн-кнопки остаются кликабельными в
истории чата, даже если конфиг, который их породил, уже другой.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module
from utils.offer import Offer  # noqa: E402


class FakeMessage:
    def __init__(self):
        self.replies: list[dict] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


class FakeQuery:
    def __init__(self):
        self.message = FakeMessage()


def _offer(*, ready: bool, url: str = "https://pay.example/checkout") -> Offer:
    return Offer(
        product_card="ЦЕНА: 4900 руб." if ready else "ЦЕНА: <<сумма>>",
        sales_block="блок",
        cta_text="cta",
        purchase_url=url,
        blockers=() if ready else ("не заполнена карточка",),
    )


@pytest.fixture
def quiet_store(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.store, "event", noop)
    monkeypatch.setattr(bot_module.store, "save", noop)


@pytest.mark.asyncio
async def test_click_gives_no_link_while_offer_unconfigured(monkeypatch, quiet_store):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=False))
    bot = bot_module.TelegramBot()
    query = FakeQuery()

    await bot._handle_offer_click(query, "1")

    sent = query.message.replies
    assert len(sent) == 1
    assert "reply_markup" not in sent[0]          # никакой кнопки с URL
    assert "pay.example" not in sent[0]["text"]   # и никакой ссылки в тексте


@pytest.mark.asyncio
async def test_click_without_checkout_url_explains_instead_of_breaking(monkeypatch, quiet_store):
    """Демо-режим: оффер настроен, оплата ещё не подключена."""
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True, url=""))
    bot = bot_module.TelegramBot()
    query = FakeQuery()

    await bot._handle_offer_click(query, "1")

    sent = query.message.replies
    assert len(sent) == 1
    assert "reply_markup" not in sent[0]
    assert "оплат" in sent[0]["text"].lower()


@pytest.mark.asyncio
async def test_click_gives_link_with_uid_when_configured(monkeypatch, quiet_store):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True))
    bot = bot_module.TelegramBot()
    query = FakeQuery()

    await bot._handle_offer_click(query, "777")

    markup = query.message.replies[0]["reply_markup"]
    url = markup.inline_keyboard[0][0].url
    assert url == "https://pay.example/checkout?uid=777"
