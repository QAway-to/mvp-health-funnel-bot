"""Отзыв: когда просим, что принимаем и что делаем с согласием.

Выдуманные отзывы на лендинге запрещены, поэтому единственный источник живых —
эта механика. Если она спрашивает не вовремя или записывает «спасибо» как
отзыв, на сайте не появится ничего, ради чего всё делалось.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.review import load_texts  # noqa: E402

TEXTS = load_texts()


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})
        return FakeMessage()


class FakeQuery:
    def __init__(self) -> None:
        self.message = FakeMessage()


@pytest.fixture
def quiet_store(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.store, "event", noop)
    monkeypatch.setattr(bot_module.store, "save", noop)


def test_all_texts_are_present():
    for key in ("request", "thanks", "ask_publish", "published_yes", "published_no"):
        assert key in TEXTS, f"нет текста {key}"


def test_the_request_promises_not_to_publish_without_consent():
    """Обещание в тексте и кнопка ниже должны совпадать."""
    assert "без твоего" in TEXTS["request"].lower()


@pytest.mark.asyncio
async def test_a_real_review_is_taken_and_consent_is_asked(quiet_store):
    bot = bot_module.TelegramBot()
    message = FakeMessage()
    await bot._ask_for_review(message, "500")

    answer = FakeMessage()
    handled = await bot._handle_review(
        answer, "500",
        "Начинал с прохладного душа, было страшно. Через два месяца обливаюсь во дворе и не болею.",
    )

    assert handled
    labels = [row[0].text for row in answer.replies[0]["reply_markup"].inline_keyboard]
    assert len(labels) == 2, "согласие спрашивается кнопками, а не текстом"


@pytest.mark.asyncio
async def test_a_short_reply_is_not_a_review(quiet_store):
    """Иначе в списке окажется десяток «спасибо» и одно настоящее мнение."""
    bot = bot_module.TelegramBot()
    await bot._ask_for_review(FakeMessage(), "501")

    handled = await bot._handle_review(FakeMessage(), "501", "спасибо!")

    assert not handled, "«спасибо» записано как отзыв"


@pytest.mark.asyncio
async def test_the_question_is_not_repeated(quiet_store):
    """Настаивать после курса — испортить впечатление, ради которого всё было."""
    bot = bot_module.TelegramBot()
    await bot._ask_for_review(FakeMessage(), "502")
    await bot._handle_review(FakeMessage(), "502", "ок")

    assert "502" not in bot._awaiting_review


@pytest.mark.asyncio
async def test_nothing_is_taken_from_someone_we_did_not_ask(quiet_store):
    bot = bot_module.TelegramBot()
    assert not await bot._handle_review(FakeMessage(), "503", "какой-то длинный текст про бег и всё такое")


@pytest.mark.asyncio
async def test_refusal_is_answered_without_pressure(quiet_store):
    bot = bot_module.TelegramBot()
    query = FakeQuery()

    await bot._handle_review_consent(query, "504", f"{bot_module._REVIEW_CALLBACK}no")

    text = query.message.replies[0]["text"].lower()
    assert "не пойдёт" in text or "только для" in text
    assert "?" not in text, "после отказа задан ещё один вопрос"
