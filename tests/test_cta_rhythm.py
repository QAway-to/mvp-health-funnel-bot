"""Как часто человек видит оффер.

Раньше — под каждым ответом, начиная с пятого сообщения. Продающий блок при
этом велит модели «второй раз к офферу в этом же диалоге не возвращаться»:
инструкция говорила одно, код делал другое, и делал это громче.

Здесь проверяется ритм: два раза за разговор, с разрывом, и ни разу тому, кто
уже заплатил.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402


def shows_at(messages: int, cta_shown: int, *, is_premium: bool = False,
             offer_ready: bool = True) -> bool:
    """Повторяет условие показа из _answer, чтобы поведение читалось числами."""
    return (
        offer_ready
        and not is_premium
        and cta_shown < bot_module._CTA_MAX_TIMES
        and messages >= bot_module._FUNNEL_CTA_AT + cta_shown * bot_module._CTA_GAP
    )


def test_silent_until_the_person_got_something():
    """До порога оффера нет: сначала польза, потом разговор о деньгах."""
    for message in range(1, bot_module._FUNNEL_CTA_AT):
        assert not shows_at(message, 0), f"оффер на {message}-м сообщении"


def test_first_offer_lands_on_the_threshold():
    assert shows_at(bot_module._FUNNEL_CTA_AT, 0)


def test_second_offer_waits_out_a_conversation():
    """Сразу за первым — это давление, а не напоминание."""
    after_first = bot_module._FUNNEL_CTA_AT + 1
    assert not shows_at(after_first, 1), "второй оффер пришёл следующим же сообщением"
    assert shows_at(bot_module._FUNNEL_CTA_AT + bot_module._CTA_GAP, 1)


def test_never_a_third_time():
    for message in range(50, 60):
        assert not shows_at(message, bot_module._CTA_MAX_TIMES), "третий показ"


def test_paying_person_is_left_alone():
    assert not shows_at(99, 0, is_premium=True)


def test_nothing_is_sold_without_a_product_card():
    assert not shows_at(99, 0, offer_ready=False)


def test_the_sales_block_promise_is_kept():
    """Инструкция модели и поведение кода не должны расходиться."""
    sales = (Path(__file__).resolve().parents[1] / "prompts" / "sales_block.txt").read_text(
        encoding="utf-8"
    )
    assert "Второй раз к офферу в этом же диалоге не возвращайся" in sales
    assert bot_module._CTA_MAX_TIMES <= 2, "код показывает чаще, чем обещает промпт"
