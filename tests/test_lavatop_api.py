"""Разбор ответа кассы и проверки перед правкой оффера.

Тут два риска, и оба про деньги. Первый: неверно разобранный ответ — и мы
правим не тот оффер. Второй: цена, которую касса примет не так, как мы имели
в виду, и человек заплатит другую сумму.

Сеть не трогаем: проверяется разбор и валидация, а не то, что LavaTop
отвечает. Формат взят из их спецификации.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import lavatop  # noqa: E402

SAMPLE = {
    "items": [
        {
            "id": "3f1c-product",
            "title": "Бег для долголетия",
            "offers": [
                {
                    "id": "aa11-offer",
                    "name": "Полный доступ",
                    "prices": [
                        {"amount": 1900, "currency": "RUB"},
                        {"amount": 19, "currency": "USD"},
                    ],
                }
            ],
        }
    ]
}


def test_products_are_parsed_with_their_offers():
    products = lavatop._parse_products(SAMPLE)
    assert len(products) == 1
    product = products[0]
    assert product.id == "3f1c-product"
    assert product.title == "Бег для долголетия"
    assert product.offers[0].id == "aa11-offer"
    assert dict(product.offers[0].prices) == {"RUB": 1900.0, "USD": 19.0}


def test_offers_wrapped_in_data_are_understood():
    """В фиде элементы приходят завёрнутыми — это тот же продукт."""
    wrapped = {"items": [{"type": "PRODUCT", "data": SAMPLE["items"][0]}]}
    assert lavatop._parse_products(wrapped)[0].id == "3f1c-product"


def test_garbage_does_not_raise():
    """Ответ не того вида — пустой список, а не исключение посреди правки."""
    for payload in ({}, {"items": "не список"}, [], None):
        assert lavatop._parse_products(payload) == ()


def test_product_without_id_is_skipped():
    assert lavatop._parse_products({"items": [{"title": "без id"}]}) == ()


# --- проверки перед отправкой цены ------------------------------------------


@pytest.mark.asyncio
async def test_unknown_currency_is_refused_before_the_request():
    with pytest.raises(lavatop.LavaError, match="валют"):
        await lavatop.update_offer("k", "p", "o", prices={"GBP": 10})


@pytest.mark.asyncio
async def test_two_currencies_are_refused():
    """Касса принимает одну валюту или все три. Две — молчаливый отказ."""
    with pytest.raises(lavatop.LavaError, match="одной валюте"):
        await lavatop.update_offer("k", "p", "o", prices={"RUB": 1900, "USD": 19})


def test_all_three_currencies_are_the_supported_set():
    assert lavatop.CURRENCIES == ("RUB", "USD", "EUR")


# --- правка оффера: соседи обязаны уехать вместе с ним -----------------------
#
# Касса на PATCH с одним оффером отвечает «You can only update existing offers»
# и не меняет ничего. Это не придирка формата: массив `offers` она понимает как
# новое состояние продукта целиком, и два непереданных плана — это заявка на их
# удаление. Тесты ниже держат ровно это.


class _FakeResponse:
    status_code = 200

    def __init__(self, sent: dict):
        self._sent = sent

    def json(self) -> dict:
        return {"title": "Федерация Здоровья", "offers": self._sent["offers"]}


class _FakeClient:
    """Перехватывает PATCH и запоминает тело. Сеть не трогается."""

    def __init__(self, box: dict, **_):
        self._box = box

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def patch(self, url, *, headers, json):
        self._box["url"] = url
        self._box["body"] = json
        return _FakeResponse(json)


THREE_PLANS = (
    lavatop.Offer("base", "База", (("USD", 9.0),), "для тех, кто идёт сам"),
    lavatop.Offer("premium", "Премиум", (("USD", 20.0),), "с обратной связью"),
    lavatop.Offer("pro", "Сопровождение", (("USD", 100.0),), "веду лично"),
)


@pytest.fixture
def cabinet(monkeypatch):
    """Кабинет с одним продуктом на три плана и перехваченный PATCH."""
    box: dict = {}

    async def fake_list(api_key):
        return (lavatop.Product("p1", "Федерация Здоровья", THREE_PLANS),)

    monkeypatch.setattr(lavatop, "list_products", fake_list)
    monkeypatch.setattr(lavatop.httpx, "AsyncClient", lambda **kw: _FakeClient(box, **kw))
    return box


@pytest.mark.asyncio
async def test_all_offers_are_sent_not_just_the_edited_one(cabinet):
    await lavatop.update_offer("k", "p1", "premium", description="новый текст")

    sent = cabinet["body"]["offers"]
    assert [o["id"] for o in sent] == ["base", "premium", "pro"], "план пропал из массива"
    assert sent[1]["description"] == "новый текст"


@pytest.mark.asyncio
async def test_neighbours_keep_their_texts_and_prices(cabinet):
    """Сосед уезжает таким, каким лежит в кабинете, — иначе правка его затрёт."""
    await lavatop.update_offer("k", "p1", "premium", description="новый текст")

    base = cabinet["body"]["offers"][0]
    assert base["name"] == "База"
    assert base["description"] == "для тех, кто идёт сам"
    assert base["prices"] == [{"amount": 9.0, "currency": "USD"}]


@pytest.mark.asyncio
async def test_untouched_fields_of_the_edited_offer_survive(cabinet):
    """«Не менять цену» для этой кассы означает «прислать ту же самую»."""
    await lavatop.update_offer("k", "p1", "pro", name="Сопровождение — $100 в месяц")

    edited = cabinet["body"]["offers"][2]
    assert edited["name"] == "Сопровождение — $100 в месяц"
    assert edited["prices"] == [{"amount": 100.0, "currency": "USD"}]
    assert edited["description"] == "веду лично"


@pytest.mark.asyncio
async def test_unknown_offer_is_refused_before_the_patch(cabinet):
    with pytest.raises(lavatop.LavaError, match="нет оффера"):
        await lavatop.update_offer("k", "p1", "нет-такого", description="…")
    assert "body" not in cabinet


@pytest.mark.asyncio
async def test_offer_description_is_read_from_the_cabinet():
    """Без разбора описания правка одного плана стирала бы текст у соседних."""
    payload = {
        "items": [
            {
                "id": "p1",
                "title": "Подписка",
                "offers": [{"id": "o1", "name": "База", "description": "текст", "prices": []}],
            }
        ]
    }
    assert lavatop._parse_products(payload)[0].offers[0].description == "текст"
