"""Markdown, просочившийся в ответ модели, чинится на выходе.

Промпт запрещает звёздочки и требует HTML-теги. Правило написано, и модель
его всё равно нарушает: markdown для неё родной. В чате это выглядит как
поломка — человек видит «**бег**» вместо жирного слова.

Ещё одна строка в промпте эту задачу не решает, поэтому решает код.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.telegram_html import has_markdown, to_telegram_html  # noqa: E402


def test_double_asterisks_become_bold():
    assert to_telegram_html("Главное в **беге** — дыхание.") == (
        "Главное в <b>беге</b> — дыхание."
    )


def test_bold_can_span_lines():
    assert to_telegram_html("**Первая\nвторая** строка") == "<b>Первая\nвторая</b> строка"


def test_underscores_become_bold_too():
    assert to_telegram_html("__важное__") == "<b>важное</b>"


def test_single_asterisks_become_italic():
    assert to_telegram_html("это *важно* понять") == "это <i>важно</i> понять"


def test_headings_lose_the_hashes():
    assert to_telegram_html("## Разминка\nтекст") == "<b>Разминка</b>\nтекст"


def test_bullets_become_dashes():
    assert to_telegram_html("* первый\n* второй") == "— первый\n— второй"


def test_bullet_and_bold_do_not_collide():
    """Маркер списка и жирный в одной строке — самый частый реальный случай."""
    assert to_telegram_html("* второй **важный** пункт") == "— второй <b>важный</b> пункт"


def test_backticks_become_code():
    assert to_telegram_html("команда `/checklist`") == "команда <code>/checklist</code>"


def test_multiplication_is_left_alone():
    """Одиночная звёздочка между числами — не разметка."""
    text = "Формула 2 * 3 * 4 остаётся как есть."
    assert to_telegram_html(text) == text


def test_correct_html_is_untouched():
    text = "Уже <b>правильный</b> тег."
    assert to_telegram_html(text) == text


def test_mixed_reply_is_fully_converted():
    reply = "Уже <b>правильный</b> тег и **неправильный**."
    assert to_telegram_html(reply) == "Уже <b>правильный</b> тег и <b>неправильный</b>."


def test_empty_input_survives():
    assert to_telegram_html("") == ""


def test_has_markdown_is_quiet_on_clean_html():
    assert has_markdown("<b>всё хорошо</b>") is False
    assert has_markdown("В ответе есть **звёздочки**") is True


def test_conversion_leaves_nothing_to_report():
    """После преобразования детектор должен молчать — иначе лог будет врать."""
    assert has_markdown(to_telegram_html("**жирный** и *курсив* и ## заголовок")) is False


ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILES = sorted(
    [*(ROOT / "prompts").glob("*.txt"), *(ROOT / "prompts" / "kb").glob("*.txt")]
)


def test_no_prompt_file_ships_markdown_bold():
    """Звёздочки вредны с обеих сторон.

    В тексте, который уходит человеку, они покажутся звёздочками. В тексте,
    который уходит модели, они её же и научат их ставить.

    Исключение одно: строка в persona.txt, которая эти символы запрещает, —
    она обязана их называть.
    """
    offenders: list[str] = []
    for path in PROMPT_FILES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "Без markdown-символов" in line:
                continue
            if "**" in line or line.lstrip().startswith("#" * 2 + " "):
                offenders.append(f"{path.name}:{number}: {line.strip()[:60]}")
    assert not offenders, "markdown в промптах:\n" + "\n".join(offenders)


def test_prompt_files_were_actually_found():
    """Пустой список файлов сделал бы предыдущую проверку бессмысленной."""
    assert len(PROMPT_FILES) >= 12
