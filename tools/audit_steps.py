"""Что реально нужно снять: шаг за шагом, с проверкой на общие ролики.

Запуск:  TASKS_SECRET=... python tools/audit_steps.py

Шаг без ролика — очевидная дыра. Шаг, который делит ролик с соседним, —
неочевидная, и именно она однажды дала неверную оценку: считались только
шаги без тега, и 52 недостающих ролика выглядели как 31.

Бот отдаёт одно и то же видео дважды, и человек решает, что курс собран
из повторов.
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

from utils.content_library import tags_for_text  # noqa: E402
from utils.steps import load_courses  # noqa: E402

KEY = os.getenv("TASKS_SECRET", "")
BASE = "https://mvp-health-funnel-bot.onrender.com/tasks/library"

#: Шаги-оговорки: они честно перечисляют, чего в курсе нет. Видео им не нужно.
NO_VIDEO_NEEDED = "чего в курсе пока нет"


def first_line(step) -> str:
    return re.sub(r"<[^>]+>", "", step.text).split("\n")[0].strip()


def main() -> None:
    if not KEY:
        sys.exit("Нужен TASKS_SECRET в окружении: разбор читает живую библиотеку.")
    library = requests.get(BASE, params={"key": KEY}, timeout=120).json()["items"]

    courses = load_courses()
    report: dict[str, list[dict]] = {}
    used: dict[int, list[str]] = defaultdict(list)

    for slug, course in courses.items():
        rows = []
        for step in course.steps:
            title = first_line(step)
            if NO_VIDEO_NEEDED in title.lower():
                rows.append({"n": step.number, "title": title, "state": "не нужен"})
                continue

            if not step.video_tags:
                rows.append({"n": step.number, "title": title, "state": "нет ролика"})
                continue

            wanted = set(tags_for_text(" ".join(step.video_tags)))
            best, score = None, 0
            # Подписчику видны все ролики, и платные, и бесплатные: так же
            # подбирает бот. Фильтр по платным завышал бы дыру.
            for item in library:
                hit = len(wanted & set(item["topics"]))
                if hit > score:
                    best, score = item, hit

            if best is None:
                rows.append({
                    "n": step.number, "title": title, "state": "тег есть, ролика нет",
                    "tags": " ".join(step.video_tags),
                })
                continue

            used[best["message_id"]].append(f"{slug}:{step.number}")
            rows.append({"n": step.number, "title": title, "state": "есть",
                         "clip": best["message_id"]})
        report[slug] = rows

    shared = {clip: steps for clip, steps in used.items() if len(steps) > 1}

    print("=== по курсам ===")
    for slug, rows in report.items():
        need = sum(1 for r in rows if r["state"] in ("нет ролика", "тег есть, ролика нет"))
        print(f"{courses[slug].title:44} шагов {len(rows):2} · снять {need:2}")

    print("\n=== шаги, делящие один ролик ===")
    if not shared:
        print("нет")
    for clip, steps in sorted(shared.items()):
        print(f"  ролик #{clip}: {', '.join(steps)}")

    total_missing = sum(
        1 for rows in report.values() for r in rows
        if r["state"] in ("нет ролика", "тег есть, ролика нет")
    )
    duplicated = sum(len(s) - 1 for s in shared.values())
    print(f"\nбез своего ролика: {total_missing}")
    print(f"повторов из-за общих роликов: {duplicated}")
    print(f"ИТОГО снять: {total_missing + duplicated}")

    out = REPO / "site" / "docs" / "steps-audit.json"
    out.write_text(json.dumps({"report": report, "shared": {str(k): v for k, v in shared.items()}},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nразбор сохранён: {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
