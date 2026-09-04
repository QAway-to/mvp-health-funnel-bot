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
from utils.funnel_stages import (  # noqa: E402
    load_stages,
    offer_turn,
    should_show_cta,
)


def shows_at(messages: int, cta_shown: int, *, is_premium: bool = False,
             offer_ready: bool = True) -> bool:
    """То же решение, что принимает _answer, — с теми же числами.

    Именно вызов, а не повторённое здесь условие: копия условия у теста уже
    была, она и осталась верной, когда оригинал в боте сломался.
    """
    return should_show_cta(
        messages=messages,
        cta_shown=cta_shown,
        turn=bot_module._OFFER_TURN,
        gap=bot_module._CTA_GAP,
        max_times=bot_module._CTA_MAX_TIMES,
        is_premium=is_premium,
        offer_ready=offer_ready,
    )


def test_silent_until_the_person_got_something():
    """До порога оффера нет: сначала польза, потом разговор о деньгах."""
    for message in range(1, bot_module._OFFER_TURN):
        assert not shows_at(message, 0), f"оффер на {message}-м сообщении"


def test_first_offer_lands_on_the_threshold():
    assert shows_at(bot_module._OFFER_TURN, 0)


def test_a_skipped_offer_turn_is_not_lost_forever():
    """Ход оффера можно проскочить, и тогда он обязан прийти следующим.

    Так и ломалось на проде: показ был завязан на равенство номеру хода. Ответ
    на нём мог упасть с ошибкой — ход при этом уже засчитан; человек мог быть
    в тот момент премиумом; а все, кто начал разговор до появления указаний,
    стояли на счётчике далеко за ним. Ни один из них не увидел бы оффер уже
    никогда: вторая ветка требует, чтобы первый показ состоялся.
    """
    for message in range(bot_module._OFFER_TURN, bot_module._OFFER_TURN + 30):
        assert shows_at(message, 0), f"оффера нет и на {message}-м сообщении"


def test_the_offer_turn_comes_from_the_instructions():
    """Число в коде и число в промпте разъезжаются — поэтому его тут нет."""
    assert bot_module._OFFER_TURN == offer_turn(load_stages())


def test_second_offer_waits_out_a_conversation():
    """Сразу за первым — это давление, а не напоминание."""
    after_first = bot_module._OFFER_TURN + 1
    assert not shows_at(after_first, 1), "второй оффер пришёл следующим же сообщением"
    assert shows_at(bot_module._OFFER_TURN + bot_module._CTA_GAP, 1)


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
