"""Обращение и длина: то, что человек чувствует раньше содержания.

Заказчик выбрал «ты» — значит «вы» в текстах бота это дефект, а не стиль.
Поймать его глазами трудно: файлов семь, правятся они по одному, и одно
«вам» в середине абзаца выглядит нормально ровно до тех пор, пока не
прочитаешь весь диалог подряд.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"

#: Тексты, которые человек читает в чате, плюс инструкции модели о том, как
#: с ним говорить. И там и там «вы» одинаково неуместно.
USER_FACING = ("welcome.txt", "offer_cta.txt", "offer_plans.txt", "followups.txt",
               "gift_checklist.txt", "sales_block.txt", "persona.txt")

_VY = re.compile(r"(?i)\b(вы|вас|вам|ваш|ваша|ваше|ваши|ваших|вашего|вашему|вами)\b")

#: Единственное законное «вы» — в самом правиле, которое его запрещает.
ALLOWED = "ОБРАЩАЙСЯ НА «ТЫ»"


def _content_lines(name: str) -> list[tuple[int, str]]:
    """Строки без комментариев: комментарии человек не читает."""
    text = (PROMPTS / name).read_text(encoding="utf-8")
    return [
        (number, line)
        for number, line in enumerate(text.splitlines(), 1)
        if not line.lstrip().startswith("#")
    ]


def test_no_formal_address_anywhere():
    offenders = []
    for name in USER_FACING:
        for number, line in _content_lines(name):
            if ALLOWED in line:
                continue
            found = _VY.search(line)
            if found:
                offenders.append(f"{name}:{number}: «{found.group(0)}» в «{line.strip()[:60]}»")
    assert not offenders, "обращение на «вы»:\n" + "\n".join(offenders)


def test_greetings_stay_short():
    """Первое сообщение читают по диагонали. Длинное закрывают, не дочитав."""
    from utils.welcome import load_welcome

    for key, greeting in load_welcome().items():
        paragraphs = [p for p in greeting.text.split("\n\n") if p.strip()]
        assert len(paragraphs) <= 4, f"{key}: абзацев {len(paragraphs)}"
        assert len(greeting.text) <= 700, f"{key}: {len(greeting.text)} знаков"


def test_followups_get_softer_not_pushier():
    """Каждое следующее догоняющее — мягче предыдущего, а не настойчивее."""
    from utils.followups import load_followups

    steps = load_followups()
    assert steps, "догоняющих сообщений нет"
    assert [s.after_hours for s in steps] == sorted(s.after_hours for s in steps)
    last = steps[-1]
    assert "последнее" in last.text.lower(), "в последнем шаге не сказано, что он последний"
