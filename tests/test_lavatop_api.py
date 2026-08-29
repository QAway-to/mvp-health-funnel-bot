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
