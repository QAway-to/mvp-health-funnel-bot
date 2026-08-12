"""Счёт в Telegram Stars.

provider_token обязателен в используемой версии библиотеки: без него вызов
падает ещё до сети, обработчик умирает, и клик по кнопке остаётся без ответа —
ровно так оффер и молчал.
"""

import inspect
import sys
from pathlib import Path

import pytest
import telegram

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402


class FakeMessage:
    def __init__(self):
        self.invoices = []

    async def reply_invoice(self, **kwargs):
        self.invoices.append(kwargs)


def test_library_still_requires_provider_token():
    """Страховка от «починили и забыли»: если аргумент станет необязательным,
    тест ниже перестанет что-либо доказывать."""
    params = inspect.signature(telegram.Bot.send_invoice).parameters
    assert params["provider_token"].default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_invoice_is_sent_with_stars_and_empty_provider():
    message = FakeMessage()

    assert await bot_module.TelegramBot()._send_invoice(message) is True

    sent = message.invoices[0]
    assert sent["currency"] == "XTR"
    assert sent["provider_token"] == ""
    assert sent["payload"] == "premium_access"
    assert sent["prices"][0].amount == bot_module._STARS_PRICE


@pytest.mark.asyncio
async def test_invoice_failure_is_reported_to_caller(monkeypatch):
    class Broken(FakeMessage):
        async def reply_invoice(self, **kwargs):
            raise bot_module.TelegramError("нет прав")

    assert await bot_module.TelegramBot()._send_invoice(Broken()) is False
