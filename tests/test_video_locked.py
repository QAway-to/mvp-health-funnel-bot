"""Что слышит человек, спросивший ровно про то, что снято, но закрыто подпиской.

До этого он не слышал ничего: `match` отбрасывает платный ролик молча, и
единственное доказательство, что за подпиской что-то стоит, пряталось как раз
от того, кому оно было нужно. Тишина в этом месте — не деликатность, а
потерянная продажа.

Обратная ошибка дороже: намёк на каждый ответ превращает разговор в витрину.
Поэтому здесь же закреплены и все случаи, когда бот обязан промолчать.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.content_library import (  # noqa: E402
    TIER_FREE,
    TIER_PREMIUM,
    ContentItem,
    ContentLibrary,
)
from utils.funnel_store import UserState  # noqa: E402
from utils.offer import Offer  # noqa: E402

PRODUCT_CARD = """НАЗВАНИЕ: Курс
ФОРМАТ: 4 недели
ЧТО ВХОДИТ:
— Программа на 4 недели
ЦЕНА: База $9, премиум $20
КОМУ НЕ ПОДОЙДЁТ: при острых болях"""


class FakeMessage:
    def __init__(self):
        self.replies: list[dict] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


class FakeUpdate:
    def __init__(self):
        self.effective_message = FakeMessage()


@pytest.fixture
def quiet_store(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.store, "event", noop)
    monkeypatch.setattr(bot_module.store, "save", noop)


@pytest.fixture
def ready_offer(monkeypatch):
    monkeypatch.setattr(bot_module, "_OFFER", Offer(
        product_card=PRODUCT_CARD, sales_block="блок", cta_text="cta",
        purchase_url="https://pay.example/checkout", blockers=(),
    ))
    monkeypatch.setattr(bot_module, "_PLANS", (
        bot_module.Plan("buy_premium", "💳 Премиум — $20", 1500),
    ))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", True)


@pytest.fixture
def premium_library(monkeypatch):
    """В библиотеке один ролик про закаливание, и он платный."""
    lib = ContentLibrary()
    lib._items = {7: ContentItem(7, ("закаливание",), TIER_PREMIUM, "Шаг 1")}
    monkeypatch.setattr(bot_module, "library", lib)
    return lib


@pytest.fixture
def texts(monkeypatch):
    monkeypatch.setattr(bot_module, "_REVIEW_TEXTS", {"video_locked": "Разбор есть — он в подписке."})


def _state(**kwargs) -> UserState:
    return UserState(chat_id="1", bucket="A", **kwargs)


async def _tease(update, state, query="как начать закаливание"):
    await bot_module.TelegramBot()._tease_locked_video(update, state, query)


# --- ради чего всё --------------------------------------------------------


@pytest.mark.asyncio
async def test_locked_video_is_announced_instead_of_silence(
    quiet_store, ready_offer, premium_library, texts
):
    update = FakeUpdate()
    await _tease(update, _state())
    assert "в подписке" in update.effective_message.replies[0]["text"]


@pytest.mark.asyncio
async def test_announcement_carries_a_way_to_buy(
    quiet_store, ready_offer, premium_library, texts
):
    """Намёк без кнопки — тупик: человеку сказали «плати», не показав куда."""
    update = FakeUpdate()
    await _tease(update, _state())
    markup = update.effective_message.replies[0]["reply_markup"]
    assert [row[0].text for row in markup.inline_keyboard] == ["💳 Премиум — $20"]


# --- когда бот обязан промолчать ------------------------------------------


@pytest.mark.asyncio
async def test_subscriber_never_hears_it(quiet_store, ready_offer, premium_library, texts):
    """Подписчику ролик просто приходит; предлагать ему купить то, что у него
    есть, — прямой путь к «за что я заплатил»."""
    update = FakeUpdate()
    await _tease(update, _state(is_premium=True))
    assert update.effective_message.replies == []


@pytest.mark.asyncio
async def test_silent_when_no_video_on_the_topic(quiet_store, ready_offer, premium_library, texts):
    """Про сон ролика нет вовсе — обещать нечего."""
    update = FakeUpdate()
    await _tease(update, _state(), query="как лучше засыпать")
    assert update.effective_message.replies == []


@pytest.mark.asyncio
async def test_silent_when_the_only_match_is_free(
    monkeypatch, quiet_store, ready_offer, texts
):
    """Бесплатный ролик не подобрался по другой причине — например, уже
    показан. Выдавать его за платный нельзя."""
    lib = ContentLibrary()
    lib._items = {7: ContentItem(7, ("закаливание",), TIER_FREE, "Шаг 1")}
    monkeypatch.setattr(bot_module, "library", lib)

    update = FakeUpdate()
    await _tease(update, _state())
    assert update.effective_message.replies == []


@pytest.mark.asyncio
async def test_silent_while_the_offer_is_not_configured(
    monkeypatch, quiet_store, premium_library, texts
):
    """Оффер не настроен — звать платить некуда."""
    monkeypatch.setattr(bot_module, "_OFFER", Offer(
        product_card="ЦЕНА: <<сумма>>", sales_block="", cta_text="",
        purchase_url="", blockers=("не заполнена карточка",),
    ))
    update = FakeUpdate()
    await _tease(update, _state())
    assert update.effective_message.replies == []


@pytest.mark.asyncio
async def test_silent_without_the_text(monkeypatch, quiet_store, ready_offer, premium_library):
    """Файла с текстом нет — молчим, а не шлём пустое сообщение."""
    monkeypatch.setattr(bot_module, "_REVIEW_TEXTS", {})
    update = FakeUpdate()
    await _tease(update, _state())
    assert update.effective_message.replies == []


@pytest.mark.asyncio
async def test_it_stops_after_two_times(quiet_store, ready_offer, premium_library, texts):
    """Дважды — напоминание, дальше — давление. Та же мерка, что у оффера."""
    telegram_bot = bot_module.TelegramBot()
    update = FakeUpdate()
    state = _state()
    for _ in range(5):
        await telegram_bot._tease_locked_video(update, state, "закаливание")
    assert len(update.effective_message.replies) == bot_module._TEASE_MAX_TIMES


def test_counter_dies_with_the_conversation(monkeypatch):
    """Счётчик не должен переживать разговор, за который он считает.

    Иначе это словарь, который растёт на каждого когда-либо написавшего и не
    уменьшается никогда, — тем же способом, каким уже успел протечь _chat_locks.
    """
    monkeypatch.setattr(bot_module, "_MAX_CONVERSATIONS", 2)
    telegram_bot = bot_module.TelegramBot()
    for chat_id in ("1", "2", "3"):
        telegram_bot._conversations[chat_id] = [{"role": "system", "content": ""}]
        telegram_bot._teased[chat_id] = 1

    telegram_bot._evict_old_chats()

    assert list(telegram_bot._conversations) == ["2", "3"]
    assert list(telegram_bot._teased) == ["2", "3"]


@pytest.mark.asyncio
async def test_the_cap_is_per_chat(quiet_store, ready_offer, premium_library, texts):
    """Счётчик одного человека не должен затыкать бота для остальных."""
    telegram_bot = bot_module.TelegramBot()
    first, second = FakeUpdate(), FakeUpdate()
    for _ in range(3):
        await telegram_bot._tease_locked_video(first, _state(), "закаливание")
    await telegram_bot._tease_locked_video(second, UserState(chat_id="2", bucket="A"), "закаливание")
    assert len(second.effective_message.replies) == 1
