"""Клик по офферу: что человек видит между «интересно» и «плачу».

Главное правило здесь одно: кнопка обещает состав и цену — значит первым
приходит состав и цена, а не счёт. Счёт вместо ответа читается так, будто
рассказывать нечего, и человек закрывает чат, не узнав, за что платит.
"""

import sys
from pathlib import Path

import pytest
from telegram.error import TelegramError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.offer import Offer  # noqa: E402

PRODUCT_CARD = """НАЗВАНИЕ: Курс
ФОРМАТ: 4 недели
ЧТО ВХОДИТ:
— Программа на 4 недели
ЦЕНА: База $9, премиум $20
КОМУ НЕ ПОДОЙДЁТ: при острых болях"""


class FakeMessage:
    def __init__(self, fail: bool = False):
        self.replies: list[dict] = []
        self.invoices: list[dict] = []
        self._fail = fail

    async def reply_text(self, text, **kwargs):
        if self._fail:
            raise TelegramError("boom")
        self.replies.append({"text": text, **kwargs})

    async def reply_invoice(self, **kwargs):
        self.invoices.append(kwargs)


class FakeQuery:
    def __init__(self):
        self.message = FakeMessage()


def _offer(*, ready: bool, url: str = "https://pay.example/checkout") -> Offer:
    return Offer(
        product_card=PRODUCT_CARD if ready else "ЦЕНА: <<сумма>>",
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


@pytest.fixture
def plans(monkeypatch):
    """Три ступени: только премиум продаётся за звёзды."""
    plans = (
        bot_module.Plan("buy_base", "💳 База — $9", 0),
        bot_module.Plan("buy_premium", "💳 Премиум — $20", 1500),
        bot_module.Plan("buy_pro", "💳 Сопровождение — $100", 0),
    )
    monkeypatch.setattr(bot_module, "_PLANS", plans)
    monkeypatch.setattr(bot_module, "_PLANS_TEXT", "Что выбираете?")
    return plans


# --- что приходит по кнопке «что входит» -----------------------------------


@pytest.mark.asyncio
async def test_click_answers_with_the_contents_before_any_payment(monkeypatch, quiet_store, plans):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", True)
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_offer_click(query, "1")

    assert query.message.invoices == []          # счёт сразу не выставляется
    first = query.message.replies[0]["text"]
    assert "Что входит" in first
    assert "Программа на 4 недели" in first
    assert "Сколько стоит" in first


@pytest.mark.asyncio
async def test_plan_buttons_carry_their_price(monkeypatch, quiet_store, plans):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", True)
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_offer_click(query, "1")

    markup = query.message.replies[1]["reply_markup"]
    labels = [row[0].text for row in markup.inline_keyboard]
    assert labels == ["💳 База — $9", "💳 Премиум — $20", "💳 Сопровождение — $100"]


@pytest.mark.asyncio
async def test_only_star_priced_plans_show_without_a_payment_page(monkeypatch, quiet_store, plans):
    """Кнопка, ведущая в извинение, хуже отсутствующей."""
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True, url=""))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", True)
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_offer_click(query, "1")

    markup = query.message.replies[1]["reply_markup"]
    assert [row[0].text for row in markup.inline_keyboard] == ["💳 Премиум — $20"]


@pytest.mark.asyncio
async def test_all_plans_offered_when_payment_goes_through_a_page(monkeypatch, quiet_store, plans):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", False)
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_offer_click(query, "1")

    markup = query.message.replies[1]["reply_markup"]
    assert len(markup.inline_keyboard) == 3


@pytest.mark.asyncio
async def test_click_gives_no_link_while_offer_unconfigured(monkeypatch, quiet_store, plans):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=False))
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_offer_click(query, "1")

    sent = query.message.replies
    assert len(sent) == 1
    assert "reply_markup" not in sent[0]          # никакой кнопки
    assert "pay.example" not in sent[0]["text"]   # и никакой ссылки в тексте


@pytest.mark.asyncio
async def test_without_any_payment_path_the_contents_still_arrive(monkeypatch, quiet_store, plans):
    """Оплаты нет — но состав человек всё равно должен увидеть."""
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True, url=""))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", False)
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_offer_click(query, "1")

    sent = query.message.replies
    assert len(sent) == 1
    assert "reply_markup" not in sent[0]
    assert "Что входит" in sent[0]["text"]
    assert "вручную" in sent[0]["text"]


# --- выбор ступени ---------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_click_sends_invoice_for_its_own_price(monkeypatch, quiet_store, plans):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", True)
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_plan_click(query, "1", plans[1])

    assert len(query.message.invoices) == 1
    assert query.message.invoices[0]["prices"][0].amount == 1500
    assert query.message.invoices[0]["title"] == "Премиум — $20"


@pytest.mark.asyncio
async def test_plan_without_stars_goes_to_the_payment_page(monkeypatch, quiet_store, plans):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", True)
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_plan_click(query, "777", plans[2])

    assert query.message.invoices == []
    url = query.message.replies[0]["reply_markup"].inline_keyboard[0][0].url
    assert url == "https://pay.example/checkout?uid=777&plan=buy_pro"


@pytest.mark.asyncio
async def test_plan_without_any_payment_path_says_so_plainly(monkeypatch, quiet_store, plans):
    monkeypatch.setattr(bot_module, "_OFFER", _offer(ready=True, url=""))
    monkeypatch.setattr(bot_module.config, "PAYMENTS_ENABLED", True)
    query = FakeQuery()

    await bot_module.TelegramBot()._handle_plan_click(query, "1", plans[0])

    assert query.message.invoices == []
    assert "напиши" in query.message.replies[0]["text"].lower()
