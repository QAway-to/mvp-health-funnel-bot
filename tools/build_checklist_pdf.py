# -*- coding: utf-8 -*-
"""Сборка чек-листа-подарка в PDF из того же текста, что уходит в Telegram.

Источник один — prompts/gift_checklist.txt. Иначе версия в чате и версия для
Instagram, сайта и печати начнут расходиться уже через пару правок, а заметит
это клиент, а не мы.

Запуск:
    python tools/build_checklist_pdf.py            # собрать assets/checklist_30_steps.pdf
    python tools/build_checklist_pdf.py --check    # только проверить, без записи
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prompts" / "gift_checklist.txt"
TARGET = ROOT / "assets" / "checklist_30_steps.pdf"
CHAT_ONLY_MARKER = "# CHAT-ONLY"

# Windows-шрифты: кириллица нужна обязательно, а встроенные в PDF базовые
# шрифты её не содержат. Список — на случай, если сборка идёт не на Windows.
FONT_CANDIDATES = (
    (Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf")),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
     Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
)

PAGE_WIDTH, PAGE_HEIGHT = fitz.paper_size("a4")
MARGIN = 56.0
LINE_HEIGHT = 1.35
TITLE_SIZE = 17.0
HEADING_SIZE = 12.0
BODY_SIZE = 10.5
TEXT_COLOR = (0.11, 0.13, 0.15)
ACCENT_COLOR = (0.12, 0.23, 0.30)


def find_fonts() -> tuple[Path, Path]:
    for regular, bold in FONT_CANDIDATES:
        if regular.exists() and bold.exists():
            return regular, bold
    raise SystemExit("Не найден шрифт с кириллицей — PDF собрать нечем")


def read_blocks(source: Path) -> list[tuple[str, str]]:
    """Разобрать текст подарка на блоки (вид, текст).

    Вид: title — заголовок документа, heading — раздел, body — обычный абзац.
    Комментарии и HTML-разметка Telegram здесь не нужны.
    """
    raw = source.read_text(encoding="utf-8")
    # Часть текста осмысленна только в переписке — например, вопрос о том, что
    # разобрать дальше. В файле она отделена меткой.
    raw = raw.split(CHAT_ONLY_MARKER, 1)[0]
    blocks: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        bold = re.fullmatch(r"<b>(.*?)</b>", line)
        text = re.sub(r"<[^>]+>", "", bold.group(1) if bold else line).strip()
        if not text:
            continue
        if bold and not blocks:
            blocks.append(("title", text))
        elif bold:
            blocks.append(("heading", text))
        else:
            blocks.append(("body", text))
    return blocks


class PdfWriter:
    """Последовательная укладка абзацев с переносом на новую страницу."""

    def __init__(self, regular: Path, bold: Path):
        self.doc = fitz.open()
        self.regular = regular
        self.bold = bold
        self.page = None
        self.y = 0.0
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = MARGIN

    def write(self, text: str, *, size: float, bold: bool, color, space_before: float) -> None:
        width = PAGE_WIDTH - 2 * MARGIN
        # Высоту считаем заранее: insert_textbox молча обрезает то, что не влезло,
        # и последние шаги чек-листа пропали бы без единой ошибки.
        needed = self._measure(text, size, bold, width)
        if self.y + space_before + needed > PAGE_HEIGHT - MARGIN:
            self._new_page()
            space_before = 0.0
        self.y += space_before
        rect = fitz.Rect(MARGIN, self.y, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - MARGIN)
        leftover = self.page.insert_textbox(
            rect, text,
            fontname="bold" if bold else "regular",
            fontfile=str(self.bold if bold else self.regular),
            fontsize=size, color=color, lineheight=LINE_HEIGHT, align=fitz.TEXT_ALIGN_LEFT,
        )
        if leftover < 0:
            raise RuntimeError("Абзац не поместился на страницу: {}".format(text[:40]))
        self.y += needed

    def _measure(self, text: str, size: float, bold: bool, width: float) -> float:
        font = fitz.Font(fontfile=str(self.bold if bold else self.regular))
        lines, current = 1, 0.0
        for word in text.split():
            word_width = font.text_length(word + " ", fontsize=size)
            if current + word_width > width:
                lines += 1
                current = word_width
            else:
                current += word_width
        return lines * size * LINE_HEIGHT

    def save(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Без этого в файл уезжает вся Arial целиком — около мегабайта на две
        # страницы. Подарок отправляют в чат и в директ, вес там заметен.
        self.doc.subset_fonts()
        self.doc.set_metadata({
            "title": "Чек-лист: 30 шагов к естественному бегу",
            "author": "Федерация Здоровья",
            "subject": "Подарок за подписку",
        })
        self.doc.save(str(target), garbage=4, deflate=True)


def build(check_only: bool = False) -> None:
    blocks = read_blocks(SOURCE)
    if not blocks:
        raise SystemExit("В prompts/gift_checklist.txt нечего собирать")

    steps = sum(1 for kind, text in blocks if kind == "body" and re.match(r"\d+\.", text))
    if steps != 30:
        raise SystemExit("Ожидалось 30 шагов, найдено {} — проверьте исходный текст".format(steps))

    writer = PdfWriter(*find_fonts())
    for index, (kind, text) in enumerate(blocks):
        if kind == "title":
            writer.write(text, size=TITLE_SIZE, bold=True, color=ACCENT_COLOR, space_before=0.0)
        elif kind == "heading":
            writer.write(text, size=HEADING_SIZE, bold=True, color=ACCENT_COLOR,
                         space_before=14.0 if index else 0.0)
        else:
            writer.write(text, size=BODY_SIZE, bold=False, color=TEXT_COLOR, space_before=4.0)

    if check_only:
        print("Проверка пройдена: {} блоков, {} шагов".format(len(blocks), steps))
        return

    writer.save(TARGET)
    size_kb = TARGET.stat().st_size / 1024
    print("Собрано: {} ({} страниц, {:.0f} КБ)".format(TARGET.name, writer.doc.page_count, size_kb))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только проверить исходный текст")
    build(check_only=parser.parse_args().check)
