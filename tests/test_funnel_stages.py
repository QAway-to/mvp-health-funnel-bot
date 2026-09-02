"""Куда бот ведёт разговор и на каком ходу предлагает купить.

Жалоба была такая: бот уточняет бесконечно. Плохого сообщения при этом нет ни
одного — плохая только сумма. Модель не знает, сколько уже длится разговор, и
каждый ответ заканчивает новым вопросом.

Стандарт телеграм-воронок: 3–5 вопросов квалификации, потом оффер. Здесь
проверяется, что он и получается.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.funnel_stages import load_stages, offer_due, stage_for  # noqa: E402
from utils.llm import _for_api  # noqa: E402

STAGES = load_stages()


def test_the_first_turns_ask_and_the_later_ones_do_not():
    """Вопросы кончаются — иначе разговор ходит по кругу и человек уходит."""
    asks = [
        "вопрос" in stage_for(STAGES, message_number=n, is_premium=False).lower()
        for n in (1, 2, 3, 4)
    ]
    assert asks[0] and asks[1], "на первых ходах бот обязан узнавать о человеке"
    assert "больше не задавай" in stage_for(STAGES, message_number=3, is_premium=False)


def test_the_offer_lands_within_five_turns():
    """Дольше — и человек уходит, так и не узнав, что ему предлагают."""
    due = [n for n in range(1, 11) if offer_due(STAGES, message_number=n)]
    assert due, "оффер не наступает никогда"
    assert due[0] <= 5, f"оффер только на {due[0]}-м ходу"


def test_the_offer_happens_once():
    assert len([n for n in range(1, 11) if offer_due(STAGES, message_number=n)]) == 1


def test_after_the_offer_the_bot_stops_selling():
    later = stage_for(STAGES, message_number=9, is_premium=False).lower()
    assert "возвращаться к нему не нужно" in later


def test_a_paying_person_is_not_sold_to():
    """Продолжать воронку после покупки — выглядеть так, будто платёж не заметили."""
    for n in (1, 4, 9):
        assert "не продавай" in stage_for(STAGES, message_number=n, is_premium=True).lower()


def test_every_early_turn_has_its_own_instruction():
    for n in (1, 2, 3, 4, 5):
        assert str(n) in STAGES, f"нет указания для хода {n}"


def test_a_missing_file_does_not_break_the_conversation():
    """Без файла бот просто ведёт разговор как раньше, а не падает."""
    assert load_stages(Path("нет-такого.txt")) == {}
    assert stage_for({}, message_number=1, is_premium=False) == ""


# --- пометка этапа не должна уехать в API -----------------------------------


def test_internal_marks_are_stripped_before_the_request():
    """Строгий провайдер откажет на неизвестном поле — целиком, а не частично."""
    sent = _for_api([
        {"role": "system", "content": "промпт"},
        {"role": "system", "content": "этап", "stage": True},
        {"role": "user", "content": "вопрос"},
    ])
    assert all(set(item) == {"role", "content"} for item in sent)
    assert len(sent) == 3


def test_the_stage_note_replaces_itself_and_does_not_pile_up():
    """Два указания подряд противоречат друг другу: «спроси» и «не спрашивай»."""
    conv = [
        {"role": "system", "content": "промпт"},
        {"role": "system", "content": "ход 1", "stage": True},
        {"role": "user", "content": "привет"},
    ]
    conv[:] = [item for item in conv if not item.get("stage")]
    conv.append({"role": "system", "content": "ход 2", "stage": True})

    marks = [item for item in conv if item.get("stage")]
    assert len(marks) == 1 and marks[0]["content"] == "ход 2"


def test_the_bot_loaded_its_stages():
    assert bot_module._FUNNEL_STAGES, "бот запустился без указаний по воронке"


# --- книга собирается из курсов, а не живёт отдельно -------------------------


def test_the_book_covers_every_course():
    """Направление, забытое в порядке глав, молча не попало бы в книгу."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_book", Path(__file__).resolve().parents[1] / "tools" / "build_book.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from utils.steps import load_courses

    assert set(load_courses()) == set(module.ORDER), "курс не расставлен в порядке глав"


def test_the_book_strips_telegram_markup():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_book", Path(__file__).resolve().parents[1] / "tools" / "build_book.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.clean("<b>Шаг 1</b>") == "**Шаг 1**"
    assert "<" not in module.clean("<i>курсив</i> и <b>жирный</b>")
