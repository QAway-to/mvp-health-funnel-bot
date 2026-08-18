"""Связки продающего блока с базой знаний и с кодом.

Продажи здесь делает модель, а не код: она ссылается на раздел базы знаний и
обещает человеку команду. Обе связки держатся только на тексте — переименовали
раздел или убрали команду, и бот начнёт отрабатывать возражения общими словами
или пошлёт за подарком в никуда. Ошибки при этом не будет ни одной.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PERSONA = (ROOT / "prompts" / "persona.txt").read_text(encoding="utf-8")
SALES = (ROOT / "prompts" / "sales_block.txt").read_text(encoding="utf-8")

OBJECTIONS_HEADING = "ВОЗРАЖЕНИЯ И ЧТО НА НИХ ОТВЕЧАТЬ"


def test_sales_block_points_at_an_existing_section():
    assert OBJECTIONS_HEADING in SALES, "продающий блок больше не ссылается на раздел возражений"
    assert f"{OBJECTIONS_HEADING}:" in PERSONA, "раздел возражений пропал из базы знаний"


def test_every_objection_has_an_answer():
    """Возражение без ответа — приглашение модели придумать его самой."""
    section = PERSONA.split(f"{OBJECTIONS_HEADING}:", 1)[1]
    quoted = [line for line in section.splitlines() if line.startswith("«")]

    assert len(quoted) >= 10, "возражений подозрительно мало"
    for line in quoted:
        answer = line.split("»", 1)[1].strip(" —")
        assert len(answer) > 40, f"нет содержательного ответа: {line[:50]}"


def test_promised_command_exists():
    """Промпт обещает /checklist — команда должна быть зарегистрирована."""
    commands = set(re.findall(r'CommandHandler\("([a-z_]+)"', (ROOT / "bot.py").read_text(encoding="utf-8")))
    for command in re.findall(r"/([a-z_]+)", SALES):
        assert command in commands, f"промпт обещает /{command}, которой нет в боте"


def test_objections_reach_the_model():
    """Раздел должен попадать в системный промпт, а не просто лежать в файле."""
    assert OBJECTIONS_HEADING in bot_module._CHAT_SYSTEM_PROMPT
