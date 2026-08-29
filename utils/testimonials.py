"""Отзывы участников — то единственное, чего в боте не хватало из воронки.

Человек верит чужому опыту раньше, чем аргументу. Пока отзывов нет, оффер
держится только на словах бота о самом себе, а это самая слабая опора из
возможных.

Тексты — в `prompts/testimonials.txt`, по разделу на отзыв. Раздел помечен
направлением, и отзыв показывается только тому, кто пришёл за этим же: отзыв
про холодную воду человеку, спрашивающему про сон, работает против нас — он
показывает, что мы говорим не с ним.

Правило, которое важнее всех остальных: **выдумывать отзывы нельзя**. Пустой
файл — рабочее состояние, просто оффер идёт без социального доказательства.
Придуманный отзыв ломает доверие ко всему остальному, а проверяется он одним
вопросом «а можно с ним связаться».
"""

from dataclasses import dataclass
from pathlib import Path

from utils.logger import log_agent_action

_PROMPTS_PATH = Path(__file__).resolve().parents[1] / "prompts" / "testimonials.txt"

_SECTION_PREFIX = "=="
#: Отзыв, который подходит любому направлению.
ANY = "all"


@dataclass(frozen=True)
class Testimonial:
    """Чужой опыт: чей и о чём."""

    #: Слаг направления или `all`.
    topic: str
    text: str


def _parse(raw: str) -> list[Testimonial]:
    sections: list[tuple[str, list[str]]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(_SECTION_PREFIX):
            topic = stripped[len(_SECTION_PREFIX) :].strip().lower()
            if topic:
                sections.append((topic, []))
            continue
        if sections:
            sections[-1][1].append(line.rstrip())

    return [
        Testimonial(topic=topic, text="\n".join(lines).strip())
        for topic, lines in sections
        if "\n".join(lines).strip()
    ]


def load_testimonials() -> tuple[Testimonial, ...]:
    try:
        raw = _PROMPTS_PATH.read_text(encoding="utf-8")
    except OSError as e:
        log_agent_action("Testimonials", f"Не прочитан testimonials.txt: {e}", level="WARNING")
        return ()

    found = tuple(_parse(raw))
    if found:
        log_agent_action("Testimonials", f"Отзывов загружено: {len(found)}")
    else:
        log_agent_action(
            "Testimonials",
            "Отзывов нет — оффер пойдёт без чужого опыта. Это хуже, но честнее выдумки",
            level="WARNING",
        )
    return found


def pick(testimonials: tuple[Testimonial, ...], source: str) -> Testimonial | None:
    """Отзыв под направление человека, иначе универсальный, иначе ничего.

    Не по кругу и не случайный: отзыв показывается рядом с оффером, а оффер
    человек видит максимум дважды. Разнообразие тут не нужно — нужен
    подходящий.
    """
    if not testimonials:
        return None

    slug = source.strip().lower()
    for item in testimonials:
        if item.topic == slug:
            return item
    for item in testimonials:
        if item.topic == ANY:
            return item
    return None
