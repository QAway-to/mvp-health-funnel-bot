"""Сверка цены в звёздах с ценой, написанной на кнопке.

Подпись ступени живёт в `prompts/offer_plans.txt` («💳 Премиум — $20»), а
сумма счёта — в переменных окружения. Связи между ними нет никакой: одно
правит тот, кто пишет тексты, другое — тот, у кого доступ к кассе.

Разъехаться они могут молча, и однажды разъехались: на кнопке стояло $20, а
счёт выставлялся на 2500 звёзд — примерно $40. Человек видит одну сумму,
платит вдвое большую, и узнаём мы об этом от него.

Поэтому при старте суммы сверяются с подписями. Не запрещаем — курс звезды
плавает, и расхождение в четверть цены нормально, — но пишем в лог, если
разошлись сильнее.
"""

import re

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


def check(plans, stars_per_dollar: float) -> list[str]:
    """Сверить ступени. Возвращает описания расхождений — пустой список, если всё сошлось.

    Ступень с нулём звёзд пропускается: это не ошибка, а «в звёздах не
    продаём», такая уходит на внешнюю страницу оплаты.
    """
    problems: list[str] = []
    for plan in plans:
        if not plan.stars:
            continue
        dollars = dollars_in(plan.title)
        if dollars is None:
            continue
        expected = expected_stars(dollars, stars_per_dollar)
        if not expected:
            continue
        drift = abs(plan.stars - expected) / expected
        if drift > TOLERANCE:
            problems.append(
                f"«{plan.title}»: на кнопке ${dollars:g}, это примерно {expected} звёзд, "
                f"а счёт выставляется на {plan.stars} — расхождение {drift:.0%}"
            )
    return problems


def log_check(plans, stars_per_dollar: float) -> None:
    problems = check(plans, stars_per_dollar)
    if not problems:
        return
    for problem in problems:
        log_agent_action("Stars", f"⚠️ Цена в звёздах не сходится с подписью: {problem}",
                         level="ERROR")
    log_agent_action(
        "Stars",
        "Поправьте STARS_PRICE_BASE / STARS_PRICE_PREMIUM / STARS_PRICE_PRO "
        "или подписи в prompts/offer_plans.txt. Человек платит по счёту, а "
        "решение принимает по подписи.",
        level="ERROR",
    )
