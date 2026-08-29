"""Работа с кабинетом LavaTop по их публичному API.

Зачем это на сервере, а не на машине разработчика: ключ от кассы уже лежит в
переменных Render, и возить его куда-то ещё незачем. Сервис ходит к API сам,
запуск идёт служебным маршрутом под тем же секретом, что рассылка.

ЧЕГО ЭТОТ API НЕ УМЕЕТ — важно знать до того, как планировать работу:

* **Создавать продукты.** В спецификации есть только список
  (`GET /api/v2/products`), правка офферов (`PATCH /api/v2/products/{id}`) и
  выставление счёта. Шесть карточек всё равно заводятся руками в кабинете.
* **Менять название и описание самого продукта.** В теле PATCH единственное
  поле `offers`; `title` и `description` продукта только читаются.

То есть автоматизировать можно ровно одно: названия офферов, их описания и
цены. Это и делается здесь.

Спецификация: https://gate.lava.top/docs/documentation.yaml
"""

from dataclasses import dataclass
from typing import Any

import httpx

from utils.logger import log_agent_action

BASE_URL = "https://gate.lava.top"
#: Валюты, которые принимает касса. Цена задаётся либо в одной, либо во всех
#: трёх — так требует их API.
CURRENCIES = ("RUB", "USD", "EUR")


class LavaError(RuntimeError):
    """Касса ответила не так, как ожидалось. Наверх идёт с текстом ответа."""


@dataclass(frozen=True)
class Offer:
    id: str
    name: str
    prices: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    offers: tuple[Offer, ...]

    def brief(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "offers": [
                {"id": o.id, "name": o.name, "prices": dict(o.prices)} for o in self.offers
            ],
        }


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Content-Type": "application/json"}


def _parse_products(payload: Any) -> tuple[Product, ...]:
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return ()

    products: list[Product] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # У фида элементы бывают завёрнуты в data — берём то, что есть.
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        offers = tuple(
            Offer(
                id=str(offer.get("id") or ""),
                name=str(offer.get("name") or ""),
                prices=tuple(
                    (str(price.get("currency") or ""), float(price.get("amount") or 0))
                    for price in (offer.get("prices") or [])
                    if isinstance(price, dict)
                ),
            )
            for offer in (data.get("offers") or [])
            if isinstance(offer, dict)
        )
        product_id = str(data.get("id") or "")
        if product_id:
            products.append(
                Product(id=product_id, title=str(data.get("title") or ""), offers=offers)
            )
    return tuple(products)


async def list_products(api_key: str) -> tuple[Product, ...]:
    """Что уже заведено в кабинете. Только чтение — ничего не меняет."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{BASE_URL}/api/v2/products",
            headers=_headers(api_key),
            params={"showAllOfferVariants": "true"},
        )
    if response.status_code != 200:
        raise LavaError(f"{response.status_code}: {response.text[:300]}")
    products = _parse_products(response.json())
    log_agent_action("Lava", f"В кабинете продуктов: {len(products)}")
    return products


async def update_offer(
    api_key: str,
    product_id: str,
    offer_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    prices: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Переписать оффер: название, описание, цены.

    Цены — либо одна валюта, либо все три, иначе касса откажет. Проверяем это
    до запроса: их ошибка приходит без объяснения, а причина всегда одна.
    """
    offer: dict[str, Any] = {"id": offer_id}
    if name is not None:
        offer["name"] = name
    if description is not None:
        offer["description"] = description
    if prices:
        unknown = set(prices) - set(CURRENCIES)
        if unknown:
            raise LavaError(f"неизвестные валюты: {sorted(unknown)}")
        if len(prices) not in (1, len(CURRENCIES)):
            raise LavaError(
                "цена задаётся либо в одной валюте, либо во всех трёх; "
                f"передано {len(prices)}"
            )
        offer["prices"] = [
            {"amount": amount, "currency": currency} for currency, amount in prices.items()
        ]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.patch(
            f"{BASE_URL}/api/v2/products/{product_id}",
            headers=_headers(api_key),
            json={"offers": [offer]},
        )
    if response.status_code >= 400:
        raise LavaError(f"{response.status_code}: {response.text[:300]}")
    log_agent_action("Lava", f"Оффер {offer_id} обновлён у продукта {product_id}")
    return response.json()
