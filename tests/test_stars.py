"""Цена в звёздах против цены на кнопке.

Сумма счёта задаётся переменными окружения, подпись ступени — текстом в
prompts/offer_plans.txt. Связи между ними нет, и однажды они разошлись вдвое:
на кнопке $20, счёт на 2500 звёзд — это около $40. Человек читает одно,
платит другое, и узнаём мы об этом от него.
"""

import sys
from dataclasses import dataclass
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
    """Главная проверка: то, что реально выставится в счёте.

    Смотрим на объявленные ступени, а не на итоговые: из итоговых расхождения
    уже сняты, и проверка сходилась бы всегда, ничего не проверяя.
    """
    assert stars.check(bot_module._DECLARED_PLANS, config.STARS_PER_DOLLAR) == []


def test_every_sold_plan_has_a_price_in_stars():
    """Оплата привязана к боту, значит ступень без звёзд просто не продаётся.

    Тоже по объявленным: ноль в итоговых — это снятое расхождение, законный
    исход, а здесь проверяется, что цена вообще задана.
    """
    for plan in bot_module._DECLARED_PLANS:
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


# --- расхождение снимает ступень со звёзд ------------------------------------
#
# Лог о расхождении уже был, и он не помог: цена в окружении перебивает
# написанную в коде, а счёт бот выставляет сам. Пока ступень остаётся
# продаваемой, «$20» на кнопке и 2500 звёзд в счёте живут вместе.


@dataclass(frozen=True)
class _Plan:
    title: str
    stars: int


def test_mismatched_plan_stops_selling_for_stars():
    plans = (_Plan("Премиум — $20", 2500),)
    assert stars.without_mismatched(plans, 62.5)[0].stars == 0


def test_matching_plan_is_left_alone():
    plans = (_Plan("Премиум — $20", 1250),)
    assert stars.without_mismatched(plans, 62.5)[0].stars == 1250


def test_small_drift_does_not_withdraw_the_plan():
    """Курс звезды плавает; в мелких пачках она дороже. Это не расхождение."""
    plans = (_Plan("Премиум — $20", 1400),)
    assert stars.without_mismatched(plans, 62.5)[0].stars == 1400


def test_only_the_broken_step_is_withdrawn():
    plans = (
        _Plan("База — $10", 625),
        _Plan("Премиум — $20", 2500),
        _Plan("Сопровождение — $100", 6250),
    )
    assert [p.stars for p in stars.without_mismatched(plans, 62.5)] == [625, 0, 6250]


def test_withdrawal_keeps_the_problem_visible_in_check():
    """Снимаем со звёзд, но не прячем: сверять надо объявленное."""
    declared = (_Plan("Премиум — $20", 2500),)
    assert stars.check(declared, 62.5), "расхождение должно остаться видимым"
    assert not stars.check(stars.without_mismatched(declared, 62.5), 62.5)
