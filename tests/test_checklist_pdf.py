"""Сборка чек-листа в PDF.

PDF и сообщение в чате собираются из одного файла, и разойтись они могут молча:
никто не заметит, что в подарке для Instagram осталось 29 шагов или что туда
уехал вопрос, адресованный собеседнику в переписке.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_checklist_pdf import CHAT_ONLY_MARKER, SOURCE, read_blocks  # noqa: E402


def test_all_thirty_steps_reach_the_pdf():
    steps = [text for kind, text in read_blocks(SOURCE)
             if kind == "body" and text[0].isdigit()]
    assert len(steps) == 30
    assert steps[0].startswith("1.")
    assert steps[-1].startswith("30.")


def test_chat_only_tail_is_cut_off():
    """Вопрос «что разберём дальше» уместен в чате и бессмыслен в файле."""
    raw = SOURCE.read_text(encoding="utf-8")
    assert CHAT_ONLY_MARKER in raw, "метка пропала — в PDF уедет лишнее"

    chat_tail = raw.split(CHAT_ONLY_MARKER, 1)[1]
    pdf_text = " ".join(text for _, text in read_blocks(SOURCE))
    for line in chat_tail.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            assert line.replace("<b>", "").replace("</b>", "") not in pdf_text


def test_markup_is_stripped():
    """HTML-теги Telegram не должны попасть в PDF как текст."""
    assert not any("<" in text for _, text in read_blocks(SOURCE))
