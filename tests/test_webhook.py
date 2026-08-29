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


# --- порядок обработки апдейтов ---------------------------------------------
#
# Баг выглядел так: человек жмёт несколько кнопок, ответы приходят вперемешку,
# каждый живёт полторы секунды и сменяется следующим. Причина — каждый апдейт
# уходил в свою задачу, и обработчики шли параллельно: ставили «⏳», ждали
# модель, удаляли свой «⏳» и слали ролик с текстом, кто когда успел.
#
# Незаметное было хуже видимого: обработчик читает состояние, ждёт модель и
# пишет состояние обратно. Параллельные затирали счётчики друг друга, а на них
# держится вся воронка.


class _Chat:
    def __init__(self, chat_id):
        self.id = chat_id


class _Update:
    def __init__(self, update_id, chat_id):
        self.update_id = update_id
        self.effective_chat = _Chat(chat_id) if chat_id is not None else None


@pytest.fixture
def ordered_bot(bot, monkeypatch):
    """Приложение, которое записывает порядок и умеет притормаживать."""
    import asyncio

    order = []

    class FakeApp:
        bot = object()
        delay = {}

        async def process_update(self, update):
            order.append(("начал", update.update_id))
            await asyncio.sleep(self.delay.get(update.update_id, 0))
            order.append(("кончил", update.update_id))

    monkeypatch.setattr(
        bot_module.Update, "de_json",
        staticmethod(lambda data, b: _Update(data["update_id"], data.get("chat"))),
    )
    bot._app = FakeApp()
    return bot, FakeApp, order


async def _drain(bot):
    for task in list(bot._update_tasks):
        await task


@pytest.mark.asyncio
async def test_updates_of_one_chat_do_not_overlap(ordered_bot):
    """Первый должен закончиться раньше, чем начнётся второй."""
    bot, app, order = ordered_bot
    app.delay = {1: 0.05}

    await bot.handle_webhook({"update_id": 1, "chat": 100}, "s3cret")
    await bot.handle_webhook({"update_id": 2, "chat": 100}, "s3cret")
    await _drain(bot)

    assert order == [("начал", 1), ("кончил", 1), ("начал", 2), ("кончил", 2)]


@pytest.mark.asyncio
async def test_different_chats_are_not_made_to_wait(ordered_bot):
    """Замок на чат, а не на бота: чужая очередь не должна тормозить всех."""
    bot, app, order = ordered_bot
    app.delay = {1: 0.05}

    await bot.handle_webhook({"update_id": 1, "chat": 100}, "s3cret")
    await bot.handle_webhook({"update_id": 2, "chat": 200}, "s3cret")
    await _drain(bot)

    assert order[:2] == [("начал", 1), ("начал", 2)], "второй чат ждал первого"


@pytest.mark.asyncio
async def test_locks_do_not_pile_up(ordered_bot):
    """Иначе словарь растёт на каждого написавшего и не уменьшается никогда."""
    bot, _, _ = ordered_bot

    for number in range(5):
        await bot.handle_webhook({"update_id": number, "chat": number}, "s3cret")
    await _drain(bot)

    assert bot._chat_locks == {}
    assert bot._chat_waiting == {}


@pytest.mark.asyncio
async def test_an_update_without_a_chat_still_goes_through(ordered_bot):
    """Правки постов и инлайн-запросы приходят без чата — это не ошибка."""
    bot, _, order = ordered_bot

    await bot.handle_webhook({"update_id": 9, "chat": None}, "s3cret")
    await _drain(bot)

    assert ("кончил", 9) in order
