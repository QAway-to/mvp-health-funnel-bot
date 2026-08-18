"""Подарок-чек-лист: выдача по команде, по кнопке и по ссылке из рекламы.

Подарок — вход в воронку: он отдаётся раньше, чем человек что-то купил, и
именно на нём держатся рекламные сценарии. Поэтому проверяем не только сам
факт отправки, но и то, что выдача попадает в аналитику: без события
невозможно посчитать конверсию из перехода в подписчика.
"""

import sys
from pathlib import Path

import pytest
from telegram.error import TelegramError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402


class FakeMessage:
    def __init__(self, fail: bool = False):
        self.replies: list[dict] = []
        self._fail = fail

    async def reply_text(self, text, **kwargs):
        if self._fail:
            raise TelegramError("boom")
        self.replies.append({"text": text, **kwargs})


@pytest.fixture
def events(monkeypatch):
    recorded: list[tuple] = []

    async def record(chat_id, name, **kwargs):
        recorded.append((chat_id, name))

    monkeypatch.setattr(bot_module.store, "event", record)
    return recorded


@pytest.mark.asyncio
async def test_gift_goes_out_and_is_counted(monkeypatch, events):
    monkeypatch.setattr(bot_module, "_GIFT_TEXT", "<b>Чек-лист</b>")
    message = FakeMessage()

    await bot_module.TelegramBot()._send_gift(message, "42")

    assert len(message.replies) == 1
    assert message.replies[0]["parse_mode"] == "HTML"
    assert events == [("42", "gift_sent")]


@pytest.mark.asyncio
async def test_empty_checklist_sends_nothing(monkeypatch, events):
    """Пустой файл — не повод молча отправить пустое сообщение."""
    monkeypatch.setattr(bot_module, "_GIFT_TEXT", "")
    message = FakeMessage()

    await bot_module.TelegramBot()._send_gift(message, "42")

    assert message.replies == []
    assert events == []


@pytest.mark.asyncio
async def test_failed_delivery_is_not_counted(monkeypatch, events):
    """Событие означает «человек получил подарок», а не «мы попытались»."""
    monkeypatch.setattr(bot_module, "_GIFT_TEXT", "<b>Чек-лист</b>")

    await bot_module.TelegramBot()._send_gift(FakeMessage(fail=True), "42")

    assert events == []


def test_checklist_fits_one_telegram_message():
    """Файл правят руками — длина не должна тихо выйти за лимит сообщения."""
    assert 0 < len(bot_module._load_gift()) <= bot_module._GIFT_LIMIT


def test_checklist_has_no_markdown_headings():
    """В Telegram markdown не отрендерится: разметка только HTML-тегами."""
    text = bot_module._load_gift()
    assert "**" not in text
    assert not any(line.startswith("#") for line in text.splitlines())
