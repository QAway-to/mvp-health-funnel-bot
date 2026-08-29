"""Сверка цены в звёздах с ценой, написанной на кнопке.

Подпись ступени живёт в `prompts/offer_plans.txt` («💳 Премиум — $20»), а
сумма счёта — в переменных окружения. Связи между ними нет никакой: одно
правит тот, кто пишет тексты, другое — тот, у кого доступ к кассе.

Разъехаться они могут молча, и однажды разъехались: на кнопке стояло $20, а
счёт выставлялся на 2500 звёзд — примерно $40. Человек видит одну сумму,
платит вдвое большую, и узнаём мы об этом от него.

Поэтому при старте суммы сверяются с подписями. Расхождение в четверть цены
нормально — курс звезды плавает и в мелких пачках она дороже. Разошлось
сильнее — ступень перестаёт продаваться за звёзды и уходит на внешнюю
страницу оплаты: не списать ничего хуже, чем списать вдвое больше, чем
человек прочитал на кнопке.

Лог при этом всё равно пишется: снятая с продажи ступень — это потерянные
деньги, и узнать о ней надо сразу, а не по отсутствию платежей.
"""

import re
from dataclasses import replace

from utils.logger import log_agent_action

#: Насколько счёт может отличаться от подписи, прежде чем это станет ошибкой.
#: Четверть — с запасом на то, что в мелких пачках звёзды дороже.
TOLERANCE = 0.25

_PRICE_IN_LABEL = re.compile(r"\$\s*(\d+(?:[.,]\d+)?)")


def dollars_in(label: str) -> float | None:
    """Цена, написанная на кнопке, или None — если её там нет."""
    found = _PRICE_IN_LABEL.search(label)
    if not found:
        return None
    return float(found.group(1).replace(",", "."))


def expected_stars(dollars: float, stars_per_dollar: float) -> int:
    return round(dollars * stars_per_dollar)


def _drift(plan, stars_per_dollar: float) -> tuple[float, int, float] | None:
    """Насколько счёт разошёлся с подписью: (доля, ожидалось звёзд, долларов).

    None — сверять нечего или всё сошлось. Ступень с нулём звёзд пропускается:
    это не ошибка, а «в звёздах не продаём».
    """
    if not plan.stars:
        return None
    dollars = dollars_in(plan.title)
    if dollars is None:
        return None
    expected = expected_stars(dollars, stars_per_dollar)
    if not expected:
        return None
    drift = abs(plan.stars - expected) / expected
    return (drift, expected, dollars) if drift > TOLERANCE else None


def check(plans, stars_per_dollar: float) -> list[str]:
    """Описания расхождений — пустой список, если всё сошлось."""
    problems: list[str] = []
    for plan in plans:
        found = _drift(plan, stars_per_dollar)
        if found is None:
            continue
        drift, expected, dollars = found
        problems.append(
            f"«{plan.title}»: на кнопке ${dollars:g}, это примерно {expected} звёзд, "
            f"а счёт выставляется на {plan.stars} — расхождение {drift:.0%}"
        )
    return problems


def without_mismatched(plans, stars_per_dollar: float) -> tuple:
    """Те же ступени, но разошедшимся выставлен ноль звёзд.

    Ноль здесь — уже существующий язык: «в звёздах не продаём, уводим на
    внешнюю страницу оплаты». Продать по неверной цене нельзя, а продать
    картой по верной — можно.
    """
    return tuple(
        replace(plan, stars=0) if _drift(plan, stars_per_dollar) else plan for plan in plans
    )


def log_check(plans, stars_per_dollar: float) -> None:
    problems = check(plans, stars_per_dollar)
    if not problems:
        return
    for problem in problems:
        log_agent_action("Stars", f"⚠️ Цена в звёздах не сходится с подписью: {problem}",
                         level="ERROR")
    log_agent_action(
        "Stars",
        "Эти ступени сняты с продажи за звёзды и уводят на внешнюю оплату. "
        "Поправьте STARS_PRICE_BASE / STARS_PRICE_PREMIUM / STARS_PRICE_PRO "
        "или подписи в prompts/offer_plans.txt. Человек платит по счёту, а "
        "решение принимает по подписи.",
        level="ERROR",
    )
