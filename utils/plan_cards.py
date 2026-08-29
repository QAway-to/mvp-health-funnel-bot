"""Карточка ступени: что человек читает перед тем, как заплатить.

Экран выбора способа оплаты — первое, что видит пришедший с лендинга по
кнопке тарифа. Раньше он состоял из названия, цены и вопроса «как удобнее
заплатить»: касса без витрины. Человек, который на сайте нажал цену, ещё
не обязательно решил — он нажал, чтобы узнать.

Поэтому карточка отвечает на три вопроса подряд: что это, что даёт именно
эта ступень, чем отличаются соседние. Последнее особенно: сама по себе цена
не значит ничего, значение ей придаёт соседняя цена рядом.

Тексты лежат в `prompts/plan_cards.txt` — там же, где остальные тексты бота,
и правятся тем, кто их пишет.
"""

from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
CARDS_FILE = "plan_cards.txt"

#: Подстановка цены: она живёт в подписи кнопки (offer_plans.txt) и не должна
#: повторяться здесь второй копией — копия разъедется, и человек прочитает
#: одну цену, а заплатит другую.
PRICE_SLOT = "{цена}"


def load_cards(path: Path | None = None) -> dict[str, str]:
    """Карточки по ступеням: `buy_base` → текст."""
    source = path or (PROMPTS / CARDS_FILE)
    if not source.is_file():
        return {}

    cards: dict[str, str] = {}
    current = ""
    lines: list[str] = []

    def flush() -> None:
        if current:
            text = "\n".join(lines).strip()
            if text:
                cards[current] = text

    for raw in source.read_text(encoding="utf-8").splitlines():
        if raw.startswith("#"):
            continue
        if raw.startswith("== "):
            flush()
            current = raw[3:].strip()
            lines = []
            continue
        lines.append(raw)
    flush()
    return cards


def card_for(cards: dict[str, str], action: str, price: str = "") -> str:
    """Текст карточки с подставленной ценой. Пусто — карточки нет."""
    text = cards.get(action, "")
    if not text:
        return ""
    return text.replace(PRICE_SLOT, price) if price else text.replace(PRICE_SLOT, "").replace("  ", " ")


def price_in(label: str) -> str:
    """Цена из подписи кнопки: «💳 Премиум — $20» → «$20».

    Берём оттуда, а не из отдельного поля: подпись — то, что человек уже
    видел, и расходиться этим двум нельзя.
    """
    for part in label.split():
        if part.startswith("$") and any(ch.isdigit() for ch in part):
            return part
    return ""
