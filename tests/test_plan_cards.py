"""Карточка ступени перед оплатой.

Это первое сообщение человека, пришедшего с лендинга по кнопке тарифа. Раньше
оно состояло из цены и вопроса «как удобнее заплатить» — касса без витрины.
Нажавший цену на сайте ещё не решил: он нажал, чтобы узнать.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.plan_cards import card_for, load_cards, price_in  # noqa: E402

CARDS = load_cards()


def test_every_sold_plan_has_a_card():
    """Ступень без карточки уходит в оплату немой."""
    for plan in bot_module._DECLARED_PLANS:
        assert plan.action in CARDS, f"нет карточки для {plan.action}"


def test_the_card_says_what_is_inside():
    card = CARDS["buy_base"]
    assert "68 шагов" in card
    assert "направлениям" in card


def test_every_card_names_the_other_levels():
    """Цена сама по себе не значит ничего — значение ей придаёт соседняя."""
    for action, card in CARDS.items():
        others = [a for a in CARDS if a != action]
        named = sum(1 for other in others if _title_of(other) in card)
        assert named == len(others), f"{action} не упоминает соседние уровни"


def _title_of(action: str) -> str:
    return {"buy_base": "База", "buy_premium": "Премиум", "buy_pro": "Сопровождение"}[action]


def test_price_comes_from_the_button_label():
    """Вторая копия цены разъедется: человек прочитает одну, заплатит другую."""
    assert price_in("💳 Премиум — $20") == "$20"
    assert price_in("Без цены") == ""


def test_the_price_is_substituted_not_hardcoded():
    for card in CARDS.values():
        assert "{цена}" in card, "цена вписана в текст вместо подстановки"


def test_card_for_fills_the_price():
    filled = card_for(CARDS, "buy_premium", "$20")
    assert "$20 в месяц" in filled
    assert "{цена}" not in filled


def test_unknown_plan_has_no_card():
    assert card_for(CARDS, "buy_nothing", "$1") == ""


def test_cards_are_html_not_markdown():
    """Сообщение уходит с parse_mode=HTML: звёздочки человек увидит как есть."""
    for action, card in CARDS.items():
        assert "**" not in card, action


def test_a_missing_file_is_not_a_crash(tmp_path):
    assert load_cards(tmp_path / "нет.txt") == {}
