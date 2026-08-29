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
* **Править один оффер в отдельности.** В `offers` идут ВСЕ офферы продукта:
  всё, чего в массиве нет, касса считает удалённым и отвечает «You can only
  update existing offers». Поэтому правка одного оффера начинается с чтения
  остальных — иначе два плана из трёх исчезли бы с витрины.

Зато можно выставить счёт (`POST /api/v3/invoice`) и прочитать продажи
(`GET /api/v1/sales/`) — на этих двух и держится выдача доступа.

То есть автоматизировать можно: названия офферов, их описания, цены, счета и
сверку оплат. Это и делается здесь.

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
class Invoice:
    """Выставленный счёт: по какой ссылке платить и как узнать этот платёж."""

    contract_id: str
    payment_url: str


@dataclass(frozen=True)
class Offer:
    id: str
    name: str
    prices: tuple[tuple[str, float], ...]
    description: str = ""

    def payload(self) -> dict[str, Any]:
        """Оффер в том виде, в каком его принимает PATCH.

        Описание кладём, только если оно у нас есть: пустая строка затёрла бы
        текст в кабинете, а соседние офферы мы здесь не правим — мы их
        сохраняем.
        """
        body: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "prices": [
                {"amount": amount, "currency": currency} for currency, amount in self.prices
            ],
        }
        if self.description:
            body["description"] = self.description
        return body


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
                {
                    "id": o.id,
                    "name": o.name,
                    "prices": dict(o.prices),
                    "description": o.description,
                }
                for o in self.offers
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
                description=str(offer.get("description") or ""),
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
    # Цены проверяем до всякой сети: ошибка кассы приходит без объяснения, а
    # причина всегда одна и та же.
    if prices:
        unknown = set(prices) - set(CURRENCIES)
        if unknown:
            raise LavaError(f"неизвестные валюты: {sorted(unknown)}")
        if len(prices) not in (1, len(CURRENCIES)):
            raise LavaError(
                "цена задаётся либо в одной валюте, либо во всех трёх; "
                f"передано {len(prices)}"
            )

    # Соседние офферы обязаны уехать вместе с правленым, иначе касса сочтёт
    # их удалёнными. Читаем их прямо перед отправкой, чтобы не отправить в
    # кабинет то, что успело устареть.
    product = next((p for p in await list_products(api_key) if p.id == product_id), None)
    if product is None:
        raise LavaError(f"продукта {product_id} нет в кабинете")
    current = next((o for o in product.offers if o.id == offer_id), None)
    if current is None:
        raise LavaError(f"у продукта {product_id} нет оффера {offer_id}")

    # Незаданные поля берём из кабинета, а не опускаем: касса требует их у
    # каждого элемента массива, и «не трогать цену» здесь означает «прислать
    # ту же самую».
    edited = Offer(
        id=offer_id,
        name=current.name if name is None else name,
        prices=(
            current.prices
            if not prices
            else tuple((currency, amount) for currency, amount in prices.items())
        ),
        description=current.description if description is None else description,
    )
    offers = [edited.payload() if o.id == offer_id else o.payload() for o in product.offers]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.patch(
            f"{BASE_URL}/api/v2/products/{product_id}",
            headers=_headers(api_key),
            json={"offers": offers},
        )
    if response.status_code >= 400:
        raise LavaError(f"{response.status_code}: {response.text[:300]}")
    log_agent_action(
        "Lava", f"Оффер {offer_id} обновлён у продукта {product_id}; всего офферов: {len(offers)}"
    )
    return response.json()


async def create_invoice(
    api_key: str,
    *,
    email: str,
    offer_id: str,
    chat_id: str,
    currency: str = "USD",
    periodicity: str = "MONTHLY",
) -> Invoice:
    """Выставить счёт и получить ссылку на оплату.

    ЗАЧЕМ ЭТО ВМЕСТО ССЫЛКИ НА ВИТРИНУ. Витрина не знает, кто пришёл: человек
    платит на странице кассы, а доступ выдаётся в Telegram, и связать одно с
    другим нечем. Счёт, выставленный отсюда, знает: `chat_id` уезжает в
    `clientUtm` и возвращается в уведомлении об оплате — касса присылает
    `clientUtm` обратно как есть. Ничего хранить не нужно.

    `utm_content` выбран не случайно: остальные поля утекают в аналитику
    рекламных кабинетов, а это — свободное.

    E-mail обязателен: на него касса шлёт чек. Он же второй способ узнать
    покупателя, если `clientUtm` почему-то не вернётся.
    """
    body = {
        "email": email,
        "offerId": offer_id,
        "currency": currency,
        "periodicity": periodicity,
        "clientUtm": {"utm_source": "telegram", "utm_content": chat_id},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{BASE_URL}/api/v3/invoice", headers=_headers(api_key), json=body
        )
    if response.status_code >= 400:
        raise LavaError(f"{response.status_code}: {response.text[:300]}")

    data = response.json()
    invoice = Invoice(
        contract_id=str(data.get("id") or ""),
        payment_url=str(data.get("paymentUrl") or ""),
    )
    if not invoice.payment_url:
        raise LavaError(f"касса не вернула ссылку оплаты: {str(data)[:200]}")
    log_agent_action("Lava", f"Счёт {invoice.contract_id} выставлен для чата {chat_id}")
    return invoice


async def has_paid(api_key: str, email: str, *, pages: int = 5) -> bool:
    """Есть ли у этой почты оплаченная покупка.

    Нужно для тех, кто заплатил на витрине, а не по счёту из бота: там
    `clientUtm` взять неоткуда, и единственное, что знают обе стороны, —
    почта. Человек называет её боту, бот спрашивает кассу.

    Спрашивать кассу, а не верить на слово: иначе доступ открывается любому,
    кто назовёт чужой адрес или просто выдумает его.
    """
    wanted = email.strip().lower()
    if not wanted:
        return False

    async with httpx.AsyncClient(timeout=30) as client:
        for page in range(pages):
            response = await client.get(
                f"{BASE_URL}/api/v1/sales/",
                headers=_headers(api_key),
                params={"page": page, "size": 100},
            )
            if response.status_code != 200:
                raise LavaError(f"{response.status_code}: {response.text[:300]}")
            payload = response.json()
            for product in payload.get("items") or []:
                for sale in (product or {}).get("sales") or []:
                    buyer = sale.get("buyer") if isinstance(sale, dict) else None
                    found = (buyer or {}).get("email") if isinstance(buyer, dict) else None
                    if str(found or "").strip().lower() == wanted:
                        return True
            if page + 1 >= int(payload.get("totalPages") or 1):
                break
    return False
