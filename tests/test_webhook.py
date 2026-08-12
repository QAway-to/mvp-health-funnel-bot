"""Вебхук — единственный способ не терять сообщения на free tier.

Спящий контейнер оживает именно от входящего запроса Telegram, поэтому важно,
чтобы этот путь не отбрасывал апдейты и не позволял стучаться посторонним.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(bot_module.config, "PUBLIC_URL", "https://svc.example.com/")
    monkeypatch.setattr(bot_module.config, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    return bot_module.TelegramBot()


def test_webhook_url_is_built_from_public_url(bot):
    assert bot.webhook_url == "https://svc.example.com/telegram/webhook"


def test_polling_is_used_when_there_is_no_public_url(monkeypatch, bot):
    monkeypatch.setattr(bot_module.config, "PUBLIC_URL", None)
    assert bot.webhook_url == ""


def test_secret_falls_back_to_token_digest(monkeypatch, bot):
    monkeypatch.setattr(bot_module.config, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(bot_module.config, "TELEGRAM_BOT_TOKEN", "123:ABC")

    secret = bot.webhook_secret

    assert len(secret) == 32 and secret != "123:ABC"


@pytest.mark.asyncio
async def test_wrong_secret_is_rejected(bot):
    assert await bot.handle_webhook({"update_id": 1}, "не тот") is False


@pytest.mark.asyncio
async def test_right_secret_is_accepted_even_without_running_app(bot):
    """Апдейт, пришедший до готовности приложения, не должен ронять запрос:
    иначе Telegram получит 500 и начнёт присылать его повторно."""
    assert await bot.handle_webhook({"update_id": 1}, "s3cret") is True


@pytest.mark.asyncio
async def test_update_processing_is_backgrounded_and_referenced(bot, monkeypatch):
    processed = []

    class FakeApp:
        bot = object()

        async def process_update(self, update):
            processed.append(update)

    monkeypatch.setattr(bot_module.Update, "de_json", staticmethod(lambda data, b: data))
    bot._app = FakeApp()

    assert await bot.handle_webhook({"update_id": 7}, "s3cret") is True
    # ссылка удержана — иначе GC вправе убить обработку на первом await
    assert len(bot._update_tasks) == 1
    for task in list(bot._update_tasks):
        await task
    assert processed == [{"update_id": 7}]
