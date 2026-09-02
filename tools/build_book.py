"""Собрать методичку из материалов, которые уже работают в продукте.

ЗАЧЕМ СБОРКА, А НЕ ОТДЕЛЬНЫЙ ФАЙЛ. Книга и курс — один и тот же материал в
двух видах. Написать книгу заново означало бы завести вторую копию: правку
делают в одном месте, и через месяц бот говорит одно, а методичка другое. В
теме здоровья это не стилистическая беда — это разная дозировка в двух местах.

Поэтому источник один: шаги курсов из `prompts/steps/`. Книга собирается из
них по команде и перестаёт быть отдельной сущностью, которую надо помнить.

ЗАПУСК

    python tools/build_book.py                  → site/docs/book.md
    python tools/build_book.py --out путь.md

Дальше markdown превращается в PDF чем угодно — от Typora до pandoc. Своего
конвертера здесь нет намеренно: он потянул бы за собой LaTeX ради задачи,
которая решается один раз в полгода.
"""

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utils.steps import load_courses  # noqa: E402

DEFAULT_OUT = REPO / "site" / "docs" / "book.md"

#: Порядок направлений в книге. Не тот, что в файлах: читателю нужен порядок
#: смысловой — от того, что делают утром, к тому, что делают потом.
ORDER = ("zaryadka", "beg", "zakalivanie", "son", "vrednye-privychki", "massazh")

INTRO = """# Федерация Здоровья

## Шесть направлений, 68 шагов

Это не сборник советов, а порядок. Что делать, в какой последовательности и в
каком объёме — чтобы привычка удержалась дольше двух недель.

Шаг — это одно действие. В боте к каждому шагу идёт короткий ролик: видео
показывает движение, текст показывает меру. Здесь собрана текстовая часть
целиком.

Здоровье не делится на курсы. Сон тянет за собой утро, утро — нагрузку,
нагрузка — восстановление. Поэтому направлений шесть, а порядок один.

**Материалы носят информационный характер.** Они не заменяют консультацию
врача. Отдельные практики — закаливание, нагрузка, массаж — имеют
противопоказания, и они названы в самих шагах. Если что-то беспокоит,
сначала врач.

---
"""


def clean(text: str) -> str:
    """HTML-разметку Telegram — в markdown."""
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.S)
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    courses = load_courses()
    unknown = set(courses) - set(ORDER)
    if unknown:
        sys.exit(
            f"Направления {sorted(unknown)} не расставлены в ORDER.\n"
            "Допишите их туда: иначе они молча не попадут в книгу."
        )

    parts = [INTRO]
    total = 0

    parts.append("## Содержание\n")
    for slug in ORDER:
        course = courses.get(slug)
        if course:
            parts.append(f"- **{course.title}** — {len(course.steps)} шагов")
    parts.append("")

    for slug in ORDER:
        course = courses.get(slug)
        if course is None:
            continue
        parts.append(f"\n---\n\n# {course.title}\n")
        for step in course.steps:
            body = clean(step.text)
            lines = [line for line in body.split("\n") if line.strip()]
            if not lines:
                continue
            heading = lines[0].strip("*").strip()
            parts.append(f"\n## {heading}\n")
            parts.extend(lines[1:])
            total += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")

    size = args.out.stat().st_size
    print(f"{args.out}: направлений {len(ORDER)}, шагов {total}, {size / 1024:.0f} КБ")
    print("Дальше: markdown → PDF любым конвертером, вёрстка не требуется.")


if __name__ == "__main__":
    main()
