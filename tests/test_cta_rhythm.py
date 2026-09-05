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

from dataclasses import replace  # noqa: E402

import bot as bot_module  # noqa: E402


def shows_at(messages: int, cta_shown: int, *, is_premium: bool = False,
             offer_ready: bool = True) -> bool:
    """То же решение, что принимает бот, — с теми же числами.

    Именно вызов, а не повторённое здесь условие: копия у теста уже была, и
    она осталась верной, когда сломался оригинал. Тесты ритма при этом
    проходили, а оффер на проде не приходил вообще никому.
    """
    state = bot_module.UserState(
        chat_id="1",
        bucket="A",
        is_premium=is_premium,
        messages=messages,
        cta_shown=cta_shown,
    )
    original = bot_module._OFFER
    bot_module._OFFER = replace(
        original, blockers=() if offer_ready else ("карточка не заполнена",)
    )
    try:
        return bot_module.should_show_cta_now(state)
    finally:
        bot_module._OFFER = original


def test_silent_until_the_person_got_something():
    """До хода оффера его нет: сначала польза, потом разговор о деньгах."""
    for message in range(1, bot_module._OFFER_TURN):
        assert not shows_at(message, 0), f"оффер на {message}-м сообщении"


def test_first_offer_lands_on_the_turn_the_instructions_name():
    assert bot_module._OFFER_TURN == 4, "в prompts/funnel_stages.txt оффер на 4-м"
    assert shows_at(bot_module._OFFER_TURN, 0)


def test_a_skipped_turn_does_not_lose_the_offer_forever():
    """Ровно то, что ломалось на проде.

    Показ был завязан на равенство номеру хода. Ход можно проскочить: ответ
    на нём мог упасть с ошибкой — он всё равно засчитан; человек мог быть в
    тот момент премиумом; а у всех, кто начал разговор до появления указаний,
    счётчик стоял далеко за ходом. Никто из них не увидел бы оффер уже
    никогда: вторая ветка требует, чтобы первый показ состоялся.
    """
    for message in range(bot_module._OFFER_TURN, bot_module._OFFER_TURN + 30):
        assert shows_at(message, 0), f"оффера нет и на {message}-м сообщении"


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
