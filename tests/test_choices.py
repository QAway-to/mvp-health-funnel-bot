"""Варианты ответа кнопками.

Кнопка обязана совпадать с вопросом. Не совпала — человек читает одно, видит
другое, и это обрывает разговор надёжнее, чем отсутствие кнопок. Поэтому
почти все проверки здесь про то, когда кнопок быть НЕ должно.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import choices  # noqa: E402


# --- явная пометка модели ---------------------------------------------------


def test_marker_gives_the_options():
    text = (
        "У тебя как с засыпанием?\n\n"
        "@варианты: засыпаю быстро | лежу и не могу выключить голову"
    )
    clean, options = choices.extract(text)
    assert options == ("Засыпаю быстро", "Лежу и не могу выключить голову")
    assert "@варианты" not in clean, "служебная строка ушла человеку"
    assert clean.strip() == "У тебя как с засыпанием?"


def test_marker_is_case_insensitive():
    _, options = choices.extract("Как спишь?\n@ВАРИАНТЫ: хорошо | плохо")
    assert options == ("Хорошо", "Плохо")


def test_more_than_three_options_are_trimmed():
    """Четыре кнопки — уже анкета, а не разговор."""
    _, options = choices.extract("Что мешает?\n@варианты: а | б | в | г")
    assert len(options) == choices.MAX_OPTIONS


def test_long_label_is_shortened():
    """Telegram обрежет длинную подпись сам, и человек не увидит, что выбирает."""
    long = "я пробовал очень много раз и каждый раз бросал примерно через неделю"
    _, options = choices.extract(f"Как было?\n@варианты: {long} | не пробовал")
    assert len(options[0]) <= choices.LABEL_LIMIT
    assert options[0].endswith("…")


# --- вопрос сам по себе кнопок не даёт --------------------------------------
#
# Запасной путь «разрежем вопрос по или» отсюда убран: первый кусок разреза
# нёс постановку вопроса, и в подпись уезжала она. Кнопки, повторяющие вопрос
# бота, — то, на что и жаловались. Без пометки вариантов нет вовсе, а под
# ответом остаются обычные кнопки тем, и разговор на этом не кончается.


def test_a_question_with_or_is_not_carved_into_buttons():
    text = "У тебя как с засыпанием — засыпаешь быстро или лежишь без сна?"
    assert choices.extract(text)[1] == ()


def test_the_question_stem_never_becomes_a_label():
    """Ровно тот случай, из-за которого путь и убран."""
    text = "Ты встаёшь на рассвете или спишь до последнего?"
    assert choices.extract(text)[1] == ()


def test_statement_without_a_question_gives_nothing():
    text = "Можно начать с прохладного душа или с обтирания."
    assert choices.extract(text)[1] == ()


def test_question_without_or_gives_nothing():
    assert choices.extract("А что тебе мешало раньше?")[1] == ()


def test_four_alternatives_are_not_buttons():
    """Длинное перечисление — это объяснение, а не выбор из двух."""
    text = "Что мешает — время или силы или боль или страх?"
    assert choices.extract(text)[1] == ()


def test_empty_and_garbage():
    for text in ("", "   ", "?", "или"):
        assert choices.extract(text)[1] == (), text


def test_the_marker_is_the_only_source():
    """Кнопка — то, что модель сформулировала как ответ, а не кусок вопроса."""
    text = "Спишь нормально или не очень?\n@варианты: сплю нормально | просыпаюсь ночью"
    _, options = choices.extract(text)
    assert options == ("Сплю нормально", "Просыпаюсь ночью")


# --- разметка не должна попадать на кнопку ----------------------------------
#
# Варианты вырезаются из ответа, который к этому моменту уже переведён в HTML.
# Сообщение Telegram разберёт, подпись кнопки — нет: на кнопке так и было
# написано «<b>Встаю на рассвете</b>».


def test_tags_are_stripped_from_marked_options():
    text = "Как утро?\n@варианты: <b>Встаю на рассвете</b> | <i>сплю до последнего</i>"
    _, options = choices.extract(text)
    assert options == ("Встаю на рассвете", "Сплю до последнего")


def test_entities_become_characters():
    _, options = choices.extract("Что выбираешь?\n@варианты: чай &amp; кофе | вода")
    assert options[0] == "Чай & кофе"


def test_length_is_measured_after_the_tags_are_gone():
    """Иначе теги съедали бы лимит, и подпись обрезалась бы на пустом месте."""
    label = "Встаю на рассвете и сразу иду на улицу"
    _, options = choices.extract(f"Как утро?\n@варианты: <b>{label}</b> | сплю")
    assert options[0] == label
