"""/testpay открывает платный доступ бесплатно — значит, он только для владельца."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, chat_id):
        self.message = FakeMessage()
        self.effective_chat = type("Chat", (), {"id": chat_id})()


@pytest.fixture
def granted(monkeypatch):
    calls = []

    async def fake_grant(self, chat_id, reason, **details):
        calls.append((chat_id, reason))

    monkeypatch.setattr(bot_module.TelegramBot, "_grant_premium", fake_grant)
    monkeypatch.setattr(bot_module.config, "ADMIN_CHAT_ID", "111")
    return calls


@pytest.mark.asyncio
async def test_stranger_cannot_grant_himself_premium(granted):
    update = FakeUpdate(999)

    await bot_module.TelegramBot()._handle_testpay(update, None)

    assert granted == []
    assert "администратора" in update.message.replies[0]


@pytest.mark.asyncio
async def test_owner_still_can_open_access_for_testing(granted):
    update = FakeUpdate(111)

    await bot_module.TelegramBot()._handle_testpay(update, None)

    assert granted == [("111", "testpay")]
