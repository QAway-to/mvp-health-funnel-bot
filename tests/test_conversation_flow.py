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
    def __init__(self, reply_markup=None) -> None:
        self.replies: list[dict] = []
        self.photos: list[str] = []
        self.deleted = False
        # Своя клавиатура — как у настоящего сообщения Telegram: именно из неё
        # достаётся подпись нажатой кнопки, и живёт она не в памяти процесса.
        self.reply_markup = reply_markup

    async def reply_text(self, text, **kwargs):
        message = FakeMessage(reply_markup=kwargs.get("reply_markup"))
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
    def __init__(self, reply_markup=None) -> None:
        self.message = FakeMessage(reply_markup=reply_markup)
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
    topics = [
        row[0] for row in markup.inline_keyboard
        if row[0].callback_data.startswith(bot_module._TOPIC_CALLBACK)
    ]
    assert topics, "кнопок с темами нет"
    for button in topics:
        assert button.callback_data.startswith("t:son:")
    # Сверху курс, снизу подарок, темы между ними.
    assert markup.inline_keyboard[0][0].callback_data.startswith(bot_module._STEP_CALLBACK)
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


# --- /start по кнопке уровня с лендинга -------------------------------------
#
# На лендинге в поп-апе есть вторая дверь — «Звёздами в Telegram». До этого она
# вела на общую страницу входа, одинаковую для всех трёх уровней: человек
# выбирал тариф на сайте и попадал туда, где надо выбирать заново. Метка
# уровня едет в deep link именно поэтому.


class _InvoiceMessage(FakeMessage):
    """Сообщение, умеющее принять счёт, — счета шлются отдельным методом."""

    def __init__(self) -> None:
        super().__init__()
        self.invoices: list[dict] = []

    async def reply_invoice(self, **kwargs):
        self.invoices.append(kwargs)


@pytest.fixture
def paying_update(monkeypatch):
    """Оплата включена, сообщение принимает счёт."""
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", True)
    update = FakeUpdate(chat_id=2101)
    update.message = _InvoiceMessage()
    return update


@pytest.mark.asyncio
async def test_tier_link_goes_straight_to_the_invoice(quiet_store, paying_update):
    await bot_module.TelegramBot()._handle_start(
        paying_update, FakeContext(["buy_premium__son"])
    )

    invoices = paying_update.message.invoices
    assert invoices, "человек выбрал уровень на сайте и не получил счёт"
    assert "$20" in invoices[0]["title"]


@pytest.mark.asyncio
async def test_the_greeting_still_comes_first(quiet_store, paying_update):
    """Счёт без единого слова в пустом чате читается как ошибка."""
    await bot_module.TelegramBot()._handle_start(
        paying_update, FakeContext(["buy_premium__son"])
    )

    assert paying_update.message.replies, "счёт пришёл в пустой чат"


@pytest.mark.asyncio
async def test_the_direction_survives_the_tier_label(quiet_store, paying_update):
    """Метка составная — направление в ней не должно потеряться."""
    await bot_module.TelegramBot()._handle_start(
        paying_update, FakeContext(["buy_base__son"])
    )

    greeting = paying_update.message.replies[0]["text"].lower()
    assert "сон" in greeting or "спать" in greeting or "выспа" in greeting


@pytest.mark.asyncio
async def test_a_plain_direction_link_does_not_start_paying(quiet_store, paying_update):
    """Старые ссылки ведут в разговор, а не в кассу."""
    await bot_module.TelegramBot()._handle_start(paying_update, FakeContext(["son"]))

    assert not paying_update.message.invoices, "человек пришёл читать, а получил счёт"


# --- варианты ответа кнопками -----------------------------------------------
#
# Написать ответ словами — работа: сформулировать, набрать, отправить. Нажать —
# не работа. На этой разнице разговор либо продолжается, либо заканчивается, и
# заканчивается он молча.


@pytest.fixture
def asking_model(monkeypatch):
    """Модель задаёт вопрос с вариантами и помечает их."""

    async def fake_completion(conversation):
        return (
            "Сон собирается из порядка, а не из одной вещи.\n\n"
            "У тебя как с засыпанием?\n"
            "@варианты: Засыпаю быстро | Лежу и не могу выключить голову"
        )

    monkeypatch.setattr(bot_module, "chat_completion", fake_completion)


@pytest.mark.asyncio
async def test_options_become_buttons(quiet_store, asking_model, no_video):
    update = FakeUpdate(chat_id=3101)

    await bot_module.TelegramBot()._answer(update, update.message, "плохо сплю")

    reply = update.message.replies[-1]
    labels = [row[0].text for row in reply["reply_markup"].inline_keyboard]
    assert labels[:2] == ["Засыпаю быстро", "Лежу и не могу выключить голову"]


@pytest.mark.asyncio
async def test_the_marker_line_never_reaches_the_person(quiet_store, asking_model, no_video):
    update = FakeUpdate(chat_id=3102)

    await bot_module.TelegramBot()._answer(update, update.message, "плохо сплю")

    assert "@варианты" not in update.message.replies[-1]["text"]


@pytest.mark.asyncio
async def test_the_way_out_is_always_last(quiet_store, asking_model, no_video):
    """Вопрос может не подходить вовсе, и без выхода уйти можно только молча."""
    update = FakeUpdate(chat_id=3103)

    await bot_module.TelegramBot()._answer(update, update.message, "плохо сплю")

    rows = update.message.replies[-1]["reply_markup"].inline_keyboard
    assert rows[-1][0].callback_data == bot_module._CHOICE_OTHER
    assert rows[-1][0].text == bot_module._CHOICE_OTHER_LABEL


@pytest.mark.asyncio
async def test_a_plain_answer_keeps_the_topic_buttons(quiet_store, captured_llm, no_video):
    """Без вопроса-выбора под ответом остаются обычные темы направления."""
    update = FakeUpdate(chat_id=3104)

    await bot_module.TelegramBot()._handle_start(update, FakeContext(["zakalivanie"]))
    await bot_module.TelegramBot()._answer(update, update.message, "как начать")

    markup = update.message.replies[-1]["reply_markup"]
    if markup is not None:
        for row in markup.inline_keyboard:
            assert not row[0].callback_data.startswith(bot_module._CHOICE_CALLBACK)


@pytest.mark.asyncio
async def test_clicking_an_option_answers_as_if_typed(quiet_store, asking_model, no_video):
    bot = bot_module.TelegramBot()
    update = FakeUpdate(chat_id=3105)
    await bot._answer(update, update.message, "плохо сплю")

    sent = update.message.replies[-1]["reply_markup"]
    query = FakeQuery(reply_markup=sent)
    await bot._handle_choice_click(update, query, "3105", f"{bot_module._CHOICE_CALLBACK}1")

    assert query.message.replies, "нажатие кнопки осталось без ответа"


@pytest.mark.asyncio
async def test_a_button_from_before_a_restart_still_answers(
    quiet_store, asking_model, no_video, monkeypatch
):
    """Кнопка вчерашнего сообщения обязана работать и после перезапуска.

    Так и ломалось: варианты лежали в памяти процесса, а контейнер на Render
    засыпает от тишины и перезапускается на каждом выкате. Человек жал
    вариант и получал «этот вопрос уже позади» — и ход разговора при этом не
    засчитывался, то есть воронка вставала на месте.
    """
    before = bot_module.TelegramBot()
    update = FakeUpdate(chat_id=3106)
    await before._answer(update, update.message, "плохо сплю")
    sent = update.message.replies[-1]["reply_markup"]

    after = bot_module.TelegramBot()          # новый процесс: памяти о вариантах нет
    query = FakeQuery(reply_markup=sent)

    # Ход разговора виден только в том, что уходит в хранилище: quiet_store
    # писать никуда не даёт, поэтому перехватываем записи здесь.
    saved: list = []

    async def record(state):
        saved.append(state)

    monkeypatch.setattr(bot_module.store, "save", record)

    await after._handle_choice_click(update, query, "3106", f"{bot_module._CHOICE_CALLBACK}0")

    texts = [reply["text"] for reply in query.message.replies]
    assert texts, "кнопка от старого сообщения промолчала"
    assert not any("уже позади" in text for text in texts), "тупик вместо ответа"
    assert saved and saved[0].messages > 0, "ход не засчитан — воронка стоит на месте"


@pytest.mark.asyncio
async def test_the_clicked_label_comes_from_the_message(quiet_store, asking_model, no_video):
    """Ответ человека — ровно та подпись, которую он видел на кнопке."""
    bot = bot_module.TelegramBot()
    update = FakeUpdate(chat_id=3107)
    await bot._answer(update, update.message, "плохо сплю")

    sent = update.message.replies[-1]["reply_markup"]
    label = sent.inline_keyboard[0][0].text
    query = FakeQuery(reply_markup=sent)

    assert bot._clicked_label(query, f"{bot_module._CHOICE_CALLBACK}0") == label


# --- воронка оплаты: сначала выбор, потом почта -----------------------------
#
# Человек, пришедший с лендинга по кнопке уровня, первым же сообщением получал
# «пришли почту». В момент самого сильного намерения — анкета. Почта нужна
# только карте, и спрашивать её до выбора способа значило спрашивать у всех.


@pytest.mark.asyncio
async def test_a_tier_link_does_not_ask_for_an_email_first(quiet_store, paying_update, monkeypatch):
    monkeypatch.setattr(bot_module.config, "LAVA_API_KEY", "fake")

    await bot_module.TelegramBot()._handle_start(
        paying_update, FakeContext(["buy_premium__son"])
    )

    texts = " ".join(reply["text"].lower() for reply in paying_update.message.replies)
    assert "почт" not in texts, "почту просят до того, как выбран способ оплаты"


@pytest.mark.asyncio
async def test_a_tier_link_shows_the_ways_to_pay(quiet_store, paying_update, monkeypatch):
    monkeypatch.setattr(bot_module.config, "LAVA_API_KEY", "fake")

    await bot_module.TelegramBot()._handle_start(
        paying_update, FakeContext(["buy_premium__son"])
    )

    markup = paying_update.message.replies[-1]["reply_markup"]
    labels = [row[0].text for row in markup.inline_keyboard]
    assert any("вёзд" in label for label in labels)
    assert any("артой" in label for label in labels)
    assert any("уровни" in label.lower() for label in labels), "нет выхода из покупки"


@pytest.mark.asyncio
async def test_the_greeting_menu_stays_quiet_while_buying(quiet_store, paying_update, monkeypatch):
    """Меню приветствия зовёт читать темы — то есть уводит от оплаты."""
    monkeypatch.setattr(bot_module.config, "LAVA_API_KEY", "fake")

    await bot_module.TelegramBot()._handle_start(
        paying_update, FakeContext(["buy_premium__son"])
    )

    greeting = paying_update.message.replies[0]
    assert greeting.get("reply_markup") is None


# --- возврат со страницы кассы ----------------------------------------------
#
# Заплатил на витрине — `chat_id` там взяться неоткуда. Единственное общее у
# кассы и бота — почта, и спросить её надо сразу: через час человек не
# вспомнит, чего от него хотели, а доступ так и не откроется.


@pytest.mark.asyncio
async def test_return_from_checkout_asks_for_the_email(quiet_store):
    update = FakeUpdate(chat_id=4101)

    await bot_module.TelegramBot()._handle_start(
        update, FakeContext([bot_module._PAID_START])
    )

    texts = " ".join(reply["text"].lower() for reply in update.message.replies)
    assert "почту" in texts, "человек вернулся из кассы и не понял, что делать"


@pytest.mark.asyncio
async def test_return_from_checkout_does_not_start_selling_again(quiet_store):
    """Он уже заплатил. Второй оффер после покупки читается как обман."""
    update = FakeUpdate(chat_id=4102)

    await bot_module.TelegramBot()._handle_start(
        update, FakeContext([bot_module._PAID_START])
    )

    texts = " ".join(reply["text"].lower() for reply in update.message.replies)
    assert "$" not in texts and "оплатить" not in texts


@pytest.mark.asyncio
async def test_an_already_open_access_is_not_asked_to_pay_again(quiet_store, monkeypatch):
    update = FakeUpdate(chat_id=4103)
    state = bot_module.store.user("4103")
    monkeypatch.setattr(
        bot_module.store, "user", lambda chat_id, **kw: replace_premium(state)
    )

    await bot_module.TelegramBot()._handle_start(
        update, FakeContext([bot_module._PAID_START])
    )

    texts = " ".join(reply["text"].lower() for reply in update.message.replies)
    assert "почту" not in texts, "у человека уже есть доступ, а его о чём-то просят"


def replace_premium(state):
    from dataclasses import replace

    return replace(state, is_premium=True)
