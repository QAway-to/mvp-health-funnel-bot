"""Цена в звёздах против цены на кнопке.

Сумма счёта задаётся переменными окружения, подпись ступени — текстом в
prompts/offer_plans.txt. Связи между ними нет, и однажды они разошлись вдвое:
на кнопке $20, счёт на 2500 звёзд — это около $40. Человек читает одно,
платит другое, и узнаём мы об этом от него.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from config import config  # noqa: E402
from utils import stars  # noqa: E402


class FakePlan:
    def __init__(self, title: str, stars_: int) -> None:
        self.title = title
        self.stars = stars_


def test_price_is_read_from_the_label():
    assert stars.dollars_in("Премиум — $20") == 20
    assert stars.dollars_in("База — $9") == 9
    assert stars.dollars_in("Без цены") is None


def test_real_plans_match_their_labels():
    """Главная проверка: то, что реально выставится в счёте."""
    assert stars.check(bot_module._PLANS, config.STARS_PER_DOLLAR) == []


def test_every_sold_plan_has_a_price_in_stars():
    """Оплата привязана к боту, значит ступень без звёзд просто не продаётся."""
    for plan in bot_module._PLANS:
        assert plan.stars > 0, f"«{plan.title}» нельзя оплатить в звёздах"


def test_the_old_mismatch_would_be_caught():
    """Тот самый случай: $20 на кнопке, 2500 звёзд в счёте."""
    problems = stars.check([FakePlan("Премиум — $20", 2500)], 62.5)
    assert len(problems) == 1
    assert "2500" in problems[0]


def test_small_drift_is_tolerated():
    """Курс звезды плавает — придираться к каждому проценту нельзя."""
    assert stars.check([FakePlan("Премиум — $20", 1300)], 62.5) == []


def test_plan_without_stars_is_not_a_problem():
    """Ноль звёзд означает «в звёздах не продаём», а не ошибку."""
    assert stars.check([FakePlan("Премиум — $20", 0)], 62.5) == []
