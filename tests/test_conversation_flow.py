"""Путь человека целиком: ссылка с лендинга → приветствие → кнопка → ответ.

Отдельные куски этого пути покрыты в других файлах: тексты приветствий, база
знаний, преобразование markdown. Здесь проверяется, что они соединены — и что
метка направления доезжает от deep link до системного промпта.

Ошибка на стыке самая дорогая и самая тихая: человек с лендинга закаливания
получает речь про бег босиком, пожимает плечами и уходит. Ни исключения, ни
строчки в логах.

Модель здесь подделана: проверяется проводка, а не качество ответов. Живой
разговор с DeepSeek этот тест не заменяет.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict] = []
        self.photos: list[str] = []
        self.deleted = False

    async def reply_text(self, text, **kwargs):
        message = FakeMessage()
        self.replies.append({"text": text, **kwargs})
        return message

    async def reply_photo(self, photo, **kwargs):
        self.photos.append(photo)

    async def delete(self):
        self.deleted = True


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeUpdate:
    def __init__(self, chat_id: int = 777) -> None:
        self.message = FakeMessage()
        self.effective_chat = FakeChat(chat_id)


class FakeQuery:
    def __init__(self) -> None:
        self.message = FakeMessage()
        self.answered = False

    async def answer(self, *args, **kwargs):
        self.answered = True


class FakeContext:
    def __init__(self, args=None) -> None:
        self.args = args or []


@pytest.fixture
def quiet_store(monkeypatch):
    """Хранилище молчит: тест про диалог, а не про Sheets."""

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.store, "event", noop)
    monkeypatch.setattr(bot_module.store, "save", noop)


@pytest.fixture
def captured_llm(monkeypatch):
    """Подделанная модель: запоминает, что ей отправили, и отвечает markdown.

    Markdown здесь намеренно: заодно проверяется, что до человека он не
    доходит.
    """
    seen: list[list[dict]] = []

    async def fake_completion(conversation):
        seen.append([dict(m) for m in conversation])
        return "Главное в **закаливании** — выйти вовремя.\n\n* первый шаг\n* второй шаг"

    monkeypatch.setattr(bot_module, "chat_completion", fake_completion)
    return seen


@pytest.fixture
def no_video(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.TelegramBot, "_send_topic_video", noop)


# --- /start с метки лендинга ------------------------------------------------


@pytest.mark.asyncio
async def test_start_from_a_landing_greets_by_that_direction(quiet_store):
    update = FakeUpdate(chat_id=1001)

    await bot_module.TelegramBot()._handle_start(update, FakeContext(["zakalivanie"]))

    greeting = update.message.replies[0]["text"]
    assert "закаливание" in greeting.lower()
    assert "бег" not in greeting.lower(), "человеку про холод рассказывают про бег"
    assert update.message.photos, "картинка приветствия не ушла"


@pytest.mark.asyncio
async def test_start_buttons_belong_to_that_direction(quiet_store):
    update = FakeUpdate(chat_id=1002)

    await bot_module.TelegramBot()._handle_start(update, FakeContext(["son"]))

    markup = update.message.replies[0]["reply_markup"]
    topics = [row[0] for row in markup.inline_keyboard[:-1]]
    assert topics, "кнопок с темами нет"
    for button in topics:
        assert button.callback_data.startswith("t:son:")
    assert markup.inline_keyboard[-1][0].callback_data == bot_module._GIFT_CALLBACK


@pytest.mark.asyncio
async def test_start_without_a_tag_falls_back_to_the_general_greeting(quiet_store):
    update = FakeUpdate(chat_id=1003)

    await bot_module.TelegramBot()._handle_start(update, FakeContext([]))

    greeting = update.message.replies[0]["text"]
    assert "шесть направлений" in greeting.lower()


# --- клик по кнопке темы ----------------------------------------------------


@pytest.mark.asyncio
async def test_topic_click_asks_the_model_that_topic(quiet_store, captured_llm, no_video):
    query = FakeQuery()
    update = FakeUpdate(chat_id=1004)

    await bot_module.TelegramBot()._handle_topic_click(update, query, "1004", "t:zakalivanie:0")

    assert captured_llm, "модель не спросили вообще"
    conversation = captured_llm[-1]
    expected = bot_module._WELCOME["zakalivanie"].topics[0]
    assert conversation[-1] == {"role": "user", "content": expected}


@pytest.mark.asyncio
async def test_topic_click_answer_reaches_the_chat(quiet_store, captured_llm, no_video):
    query = FakeQuery()
    update = FakeUpdate(chat_id=1005)

    await bot_module.TelegramBot()._handle_topic_click(update, query, "1005", "t:zakalivanie:0")

    texts = [reply["text"] for reply in query.message.replies]
    answer = [t for t in texts if t != "⏳"]
    assert answer, "ответ модели до чата не дошёл"


@pytest.mark.asyncio
async def test_markdown_from_the_model_never_reaches_the_reader(
    quiet_store, captured_llm, no_video
):
    query = FakeQuery()
    update = FakeUpdate(chat_id=1006)

    await bot_module.TelegramBot()._handle_topic_click(update, query, "1006", "t:zakalivanie:1")

    answer = [r["text"] for r in query.message.replies if r["text"] != "⏳"][0]
    assert "**" not in answer, "человек увидит звёздочки вместо жирного"
    assert "<b>закаливании</b>" in answer
    assert "— первый шаг" in answer


# --- что именно уходит модели ----------------------------------------------


@pytest.mark.asyncio
async def test_system_prompt_carries_the_direction_and_its_knowledge(
    monkeypatch, quiet_store, captured_llm, no_video
):
    """Метка направления и факты по нему должны доехать до модели вместе."""
    monkeypatch.setattr(
        bot_module.store,
        "user",
        lambda chat_id, **kw: bot_module.UserState(chat_id=chat_id, bucket="a", source="zakalivanie"),
    )
    update = FakeUpdate(chat_id=1007)

    await bot_module.TelegramBot()._answer(update, update.message, "с чего начать?")

    system = captured_llm[-1][0]
    assert system["role"] == "system"
    assert "ОТКУДА ПРИШЁЛ ЭТОТ ЧЕЛОВЕК" in system["content"]
    assert "Закаливание" in system["content"]
    assert "НАПРАВЛЕНИЕ: ЗАКАЛИВАНИЕ" in system["content"]
    assert "ЧЕГО НЕТ В БАЗЕ ЗНАНИЙ" in system["content"]


@pytest.mark.asyncio
async def test_typed_message_and_button_share_one_path(
    monkeypatch, quiet_store, captured_llm, no_video
):
    """Два входа — один код. Разойдутся — разойдутся и молча."""
    monkeypatch.setattr(
        bot_module.store,
        "user",
        lambda chat_id, **kw: bot_module.UserState(chat_id=chat_id, bucket="a", source="son"),
    )
    typed = FakeUpdate(chat_id=1)
    await bot_module.TelegramBot()._answer(typed, typed.message, "как заснуть?")

    clicked = FakeUpdate(chat_id=2)
    query = FakeQuery()
    await bot_module.TelegramBot()._handle_topic_click(clicked, query, "2", "t:son:0")

    assert captured_llm[0][0]["content"] == captured_llm[1][0]["content"]
